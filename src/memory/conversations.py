"""会话元数据持久化。"""

from __future__ import annotations

import re
from datetime import datetime

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def build_conversation_title(message: str, max_length: int = 30) -> str:
    """从首条消息生成会话标题。"""
    normalized = re.sub(r"\s+", " ", message).strip()
    if not normalized:
        return "新会话"
    return normalized[:max_length]


def _serialize_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_summary(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "thread_id": row["thread_id"],
        "user_id": row.get("user_id"),
        "title": row.get("title") or "新会话",
        "channel": row.get("channel") or "web",
        "created_at": _serialize_timestamp(row.get("created_at")),
        "last_message_at": _serialize_timestamp(row.get("last_message_at")),
        "message_count": row.get("message_count", 0),
        "is_deleted": bool(row.get("is_deleted", False)),
        "deleted_at": _serialize_timestamp(row.get("deleted_at")),
    }


class ConversationStore:
    """会话元数据存储。"""

    def __init__(self):
        self._pool = None
        self._schema_ready = False
        self._disabled_reason: str | None = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("会话元数据存储已降级", reason=reason, error=error)
            self._logged_disabled_reason = True

    async def _get_pool(self):
        if self._disabled_reason:
            return None

        if self._pool is None:
            try:
                import asyncpg
            except ModuleNotFoundError as e:
                self._disable("asyncpg_unavailable", error=str(e))
                return None

            try:
                self._pool = await asyncpg.create_pool(
                    host=settings.postgres_host,
                    port=settings.postgres_port,
                    database=settings.postgres_db,
                    user=settings.postgres_user,
                    password=settings.postgres_password,
                    max_size=10,
                )
            except Exception as e:
                self._disable("pool_init_failed", error=str(e))
                return None

        if not self._schema_ready:
            await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        pool = self._pool
        if pool is None or self._schema_ready:
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_metadata (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255),
                    title VARCHAR(500),
                    channel VARCHAR(50) DEFAULT 'web',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    last_message_at TIMESTAMPTZ DEFAULT NOW(),
                    message_count INTEGER DEFAULT 0,
                    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    deleted_at TIMESTAMPTZ
                )
                """
            )
            await conn.execute(
                """
                ALTER TABLE conversation_metadata
                ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            await conn.execute(
                """
                ALTER TABLE conversation_metadata
                ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active
                ON conversation_metadata(user_id, is_deleted, last_message_at DESC)
                """
            )
        self._schema_ready = True

    async def _fetchrow(self, query: str, *args):
        pool = await self._get_pool()
        if pool is None:
            return None
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def _fetch(self, query: str, *args):
        pool = await self._get_pool()
        if pool is None:
            return []
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def _execute(self, query: str, *args):
        pool = await self._get_pool()
        if pool is None:
            return ""
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def upsert_on_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        channel: str,
        increment: int = 2,
    ) -> dict:
        title = build_conversation_title(message)
        row = await self._fetchrow(
            """
            INSERT INTO conversation_metadata (
                thread_id, user_id, title, channel, message_count, is_deleted, deleted_at
            )
            VALUES ($1, $2, $3, $4, $5, FALSE, NULL)
            ON CONFLICT (thread_id) DO UPDATE
            SET user_id = EXCLUDED.user_id,
                channel = EXCLUDED.channel,
                last_message_at = NOW(),
                message_count = conversation_metadata.message_count + EXCLUDED.message_count,
                is_deleted = FALSE,
                deleted_at = NULL,
                title = CASE
                    WHEN conversation_metadata.title IS NULL
                        OR conversation_metadata.title = ''
                    THEN EXCLUDED.title
                    ELSE conversation_metadata.title
                END
            RETURNING
                thread_id,
                user_id,
                title,
                channel,
                created_at,
                last_message_at,
                message_count,
                is_deleted,
                deleted_at
            """,
            thread_id,
            user_id,
            title,
            channel,
            increment,
        )
        return _row_to_summary(row) or {}

    async def list_by_user(self, user_id: str, limit: int = 20, offset: int = 0) -> dict:
        rows = await self._fetch(
            """
            SELECT thread_id, user_id, title, channel, created_at, last_message_at,
                   message_count, is_deleted, deleted_at
            FROM conversation_metadata
            WHERE user_id = $1 AND is_deleted = FALSE
            ORDER BY last_message_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            limit,
            offset,
        )
        count_row = await self._fetchrow(
            """
            SELECT COUNT(*) AS total
            FROM conversation_metadata
            WHERE user_id = $1 AND is_deleted = FALSE
            """,
            user_id,
        )
        return {
            "items": [_row_to_summary(dict(row)) for row in rows],
            "total": int(count_row["total"]) if count_row else 0,
        }

    async def get_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        include_deleted: bool = False,
    ) -> dict | None:
        conditions = ["thread_id = $1"]
        args: list = [thread_id]
        arg_index = 2
        if user_id is not None:
            conditions.append(f"user_id = ${arg_index}")
            args.append(user_id)
            arg_index += 1
        if not include_deleted:
            conditions.append("is_deleted = FALSE")

        row = await self._fetchrow(
            f"""
            SELECT thread_id, user_id, title, channel, created_at, last_message_at,
                   message_count, is_deleted, deleted_at
            FROM conversation_metadata
            WHERE {' AND '.join(conditions)}
            """,
            *args,
        )
        return _row_to_summary(row)

    async def rename(self, thread_id: str, user_id: str, title: str) -> dict | None:
        row = await self._fetchrow(
            """
            UPDATE conversation_metadata
            SET title = $3
            WHERE thread_id = $1 AND user_id = $2 AND is_deleted = FALSE
            RETURNING
                thread_id,
                user_id,
                title,
                channel,
                created_at,
                last_message_at,
                message_count,
                is_deleted,
                deleted_at
            """,
            thread_id,
            user_id,
            title.strip(),
        )
        return _row_to_summary(row)

    async def soft_delete(self, thread_id: str, user_id: str) -> bool:
        status = await self._execute(
            """
            UPDATE conversation_metadata
            SET is_deleted = TRUE, deleted_at = NOW()
            WHERE thread_id = $1 AND user_id = $2 AND is_deleted = FALSE
            """,
            thread_id,
            user_id,
        )
        return status.endswith("1")

    async def close(self):
        if self._pool:
            await self._pool.close()


async def record_conversation_turn(
    *,
    thread_id: str,
    user_id: str,
    message: str,
    channel: str,
) -> None:
    """记录一次成功完成的对话。"""
    if not user_id or not thread_id:
        return
    try:
        store = get_conversation_store()
        await store.upsert_on_turn(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            channel=channel,
        )
    except Exception as e:
        logger.warning(
            "记录会话元数据失败",
            thread_id=thread_id,
            user_id=user_id,
            error=str(e),
        )


_conversation_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store
