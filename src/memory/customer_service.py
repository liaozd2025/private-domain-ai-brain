"""客服消息与人工接管持久化。"""

from __future__ import annotations

from datetime import datetime

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

STANDARD_HANDOFF_MESSAGE = "这个问题我暂时无法准确回答，已为您转接人工客服，请稍候。"
ACTIVE_HANDOFF_MESSAGE = "人工客服正在处理中，请稍候。"


def _serialize_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_handoff(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "user_id": row["user_id"],
        "channel": row["channel"],
        "status": row["status"],
        "reason": row.get("reason"),
        "last_customer_message": row.get("last_customer_message"),
        "claimed_by": row.get("claimed_by"),
        "claimed_at": _serialize_timestamp(row.get("claimed_at")),
        "resolved_at": _serialize_timestamp(row.get("resolved_at")),
        "created_at": _serialize_timestamp(row.get("created_at")),
        "updated_at": _serialize_timestamp(row.get("updated_at")),
    }


def _row_to_message(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "thread_id": row["thread_id"],
        "user_id": row["user_id"],
        "channel": row["channel"],
        "sender_type": row["sender_type"],
        "content": row["content"],
        "created_at": _serialize_timestamp(row.get("created_at")),
    }


class CustomerServiceStore:
    """客服消息与人工接管存储。"""

    def __init__(self):
        self._pool = None
        self._schema_ready = False
        self._disabled_reason: str | None = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("客服存储已降级", reason=reason, error=error)
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
                CREATE TABLE IF NOT EXISTS customer_service_messages (
                    id BIGSERIAL PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    channel VARCHAR(50) NOT NULL DEFAULT 'web',
                    sender_type VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_customer_service_messages_thread
                ON customer_service_messages(thread_id, created_at ASC)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS human_handoffs (
                    id VARCHAR(255) PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    channel VARCHAR(50) NOT NULL DEFAULT 'web',
                    status VARCHAR(20) NOT NULL,
                    reason TEXT,
                    last_customer_message TEXT,
                    claimed_by VARCHAR(255),
                    claimed_at TIMESTAMPTZ,
                    resolved_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_human_handoffs_status
                ON human_handoffs(status, updated_at DESC)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_human_handoffs_thread
                ON human_handoffs(thread_id, updated_at DESC)
                """
            )
            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_human_handoffs_active_thread
                ON human_handoffs(thread_id)
                WHERE status IN ('pending', 'claimed')
                """
            )
            await conn.execute(
                """
                ALTER TABLE conversation_metadata
                ADD COLUMN IF NOT EXISTS user_role VARCHAR(50) DEFAULT 'unknown'
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

    async def append_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        channel: str,
        sender_type: str,
        content: str,
    ) -> dict | None:
        row = await self._fetchrow(
            """
            INSERT INTO customer_service_messages (
                thread_id, user_id, channel, sender_type, content
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, thread_id, user_id, channel, sender_type, content, created_at
            """,
            thread_id,
            user_id,
            channel,
            sender_type,
            content,
        )
        return _row_to_message(row)

    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        conditions = ["thread_id = $1"]
        args: list = [thread_id]
        arg_index = 2
        if user_id is not None:
            conditions.append(f"user_id = ${arg_index}")
            args.append(user_id)
            arg_index += 1
        args.append(limit)
        rows = await self._fetch(
            f"""
            SELECT id, thread_id, user_id, channel, sender_type, content, created_at
            FROM customer_service_messages
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at ASC
            LIMIT ${arg_index}
            """,
            *args,
        )
        return [_row_to_message(dict(row)) for row in rows]

    async def is_customer_thread(self, thread_id: str, *, user_id: str | None = None) -> bool:
        conditions = ["thread_id = $1"]
        args: list = [thread_id]
        arg_index = 2
        if user_id is not None:
            conditions.append(f"user_id = ${arg_index}")
            args.append(user_id)
            arg_index += 1
        message_row = await self._fetchrow(
            f"""
            SELECT 1 AS exists_flag
            FROM customer_service_messages
            WHERE {' AND '.join(conditions)}
            LIMIT 1
            """,
            *args,
        )
        if message_row:
            return True

        # Use a fresh index for the second query
        metadata_conditions = ["thread_id = $1", "user_role = 'customer'"]
        metadata_args: list = [thread_id]
        metadata_arg_index = 2
        if user_id is not None:
            metadata_conditions.append(f"user_id = ${metadata_arg_index}")
            metadata_args.append(user_id)
        metadata_row = await self._fetchrow(
            f"""
            SELECT 1 AS exists_flag
            FROM conversation_metadata
            WHERE {' AND '.join(metadata_conditions)}
            LIMIT 1
            """,
            *metadata_args,
        )
        return bool(metadata_row)

    async def get_active_handoff(self, thread_id: str) -> dict | None:
        row = await self._fetchrow(
            """
            SELECT id, thread_id, user_id, channel, status, reason,
                   last_customer_message, claimed_by, claimed_at, resolved_at,
                   created_at, updated_at
            FROM human_handoffs
            WHERE thread_id = $1 AND status IN ('pending', 'claimed')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            thread_id,
        )
        return _row_to_handoff(row)

    async def create_or_refresh_handoff(
        self,
        *,
        thread_id: str,
        user_id: str,
        channel: str,
        reason: str,
        last_customer_message: str,
    ) -> dict | None:
        active = await self.get_active_handoff(thread_id)
        if active:
            row = await self._fetchrow(
                """
                UPDATE human_handoffs
                SET reason = $2,
                    last_customer_message = $3,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING id, thread_id, user_id, channel, status, reason,
                          last_customer_message, claimed_by, claimed_at, resolved_at,
                          created_at, updated_at
                """,
                active["id"],
                reason,
                last_customer_message,
            )
            return _row_to_handoff(row)

        row = await self._fetchrow(
            """
            INSERT INTO human_handoffs (
                id, thread_id, user_id, channel, status, reason, last_customer_message
            )
            VALUES (
                $1, $2, $3, $4, 'pending', $5, $6
            )
            RETURNING id, thread_id, user_id, channel, status, reason,
                      last_customer_message, claimed_by, claimed_at, resolved_at,
                      created_at, updated_at
            """,
            f"handoff_{thread_id}",
            thread_id,
            user_id,
            channel,
            reason,
            last_customer_message,
        )
        return _row_to_handoff(row)

    async def list_handoffs(
        self,
        *,
        status: str | None = None,
        channel: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        conditions = ["1 = 1"]
        args: list = []
        if status:
            args.append(status)
            conditions.append(f"status = ${len(args)}")
        if channel:
            args.append(channel)
            conditions.append(f"channel = ${len(args)}")

        args_with_page = [*args, limit, offset]
        rows = await self._fetch(
            f"""
            SELECT id, thread_id, user_id, channel, status, reason,
                   last_customer_message, claimed_by, claimed_at, resolved_at,
                   created_at, updated_at
            FROM human_handoffs
            WHERE {' AND '.join(conditions)}
            ORDER BY updated_at DESC
            LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
            """,
            *args_with_page,
        )
        count_row = await self._fetchrow(
            f"""
            SELECT COUNT(*) AS total
            FROM human_handoffs
            WHERE {' AND '.join(conditions)}
            """,
            *args,
        )
        return {
            "items": [_row_to_handoff(dict(row)) for row in rows],
            "total": int(count_row["total"]) if count_row else 0,
        }

    async def get_handoff_detail(self, handoff_id: str) -> dict | None:
        row = await self._fetchrow(
            """
            SELECT id, thread_id, user_id, channel, status, reason,
                   last_customer_message, claimed_by, claimed_at, resolved_at,
                   created_at, updated_at
            FROM human_handoffs
            WHERE id = $1
            """,
            handoff_id,
        )
        handoff = _row_to_handoff(row)
        if not handoff:
            return None
        handoff["messages"] = await self.get_thread_messages(
            handoff["thread_id"],
            user_id=handoff["user_id"],
            limit=200,
        )
        return handoff

    async def claim_handoff(self, *, handoff_id: str, agent_id: str) -> dict | None:
        row = await self._fetchrow(
            """
            UPDATE human_handoffs
            SET status = 'claimed',
                claimed_by = $2,
                claimed_at = COALESCE(claimed_at, NOW()),
                updated_at = NOW()
            WHERE id = $1 AND status IN ('pending', 'claimed')
            RETURNING id, thread_id, user_id, channel, status, reason,
                      last_customer_message, claimed_by, claimed_at, resolved_at,
                      created_at, updated_at
            """,
            handoff_id,
            agent_id,
        )
        return _row_to_handoff(row)

    async def reply_to_handoff(
        self,
        *,
        handoff_id: str,
        agent_id: str,
        content: str,
        resolve_after_reply: bool = False,
    ) -> dict | None:
        handoff = await self.claim_handoff(handoff_id=handoff_id, agent_id=agent_id)
        if not handoff:
            return None

        await self.append_message(
            thread_id=handoff["thread_id"],
            user_id=handoff["user_id"],
            channel=handoff["channel"],
            sender_type="human",
            content=content,
        )

        if resolve_after_reply:
            return await self.resolve_handoff(
                handoff_id=handoff_id,
                agent_id=agent_id,
                resolution_note="人工回复后结束接管",
            )

        row = await self._fetchrow(
            """
            UPDATE human_handoffs
            SET updated_at = NOW()
            WHERE id = $1
            RETURNING id, thread_id, user_id, channel, status, reason,
                      last_customer_message, claimed_by, claimed_at, resolved_at,
                      created_at, updated_at
            """,
            handoff_id,
        )
        return _row_to_handoff(row)

    async def resolve_handoff(
        self,
        *,
        handoff_id: str,
        agent_id: str,
        resolution_note: str,
    ) -> dict | None:
        row = await self._fetchrow(
            """
            UPDATE human_handoffs
            SET status = 'resolved',
                claimed_by = COALESCE(claimed_by, $2),
                claimed_at = COALESCE(claimed_at, NOW()),
                resolved_at = NOW(),
                updated_at = NOW()
            WHERE id = $1 AND status IN ('pending', 'claimed')
            RETURNING id, thread_id, user_id, channel, status, reason,
                      last_customer_message, claimed_by, claimed_at, resolved_at,
                      created_at, updated_at
            """,
            handoff_id,
            agent_id,
        )
        handoff = _row_to_handoff(row)
        if handoff and resolution_note:
            await self.append_message(
                thread_id=handoff["thread_id"],
                user_id=handoff["user_id"],
                channel=handoff["channel"],
                sender_type="system",
                content=resolution_note,
            )
        return handoff

    async def close(self):
        if self._pool:
            await self._pool.close()


_customer_service_store: CustomerServiceStore | None = None


def get_customer_service_store() -> CustomerServiceStore:
    global _customer_service_store
    if _customer_service_store is None:
        _customer_service_store = CustomerServiceStore()
    return _customer_service_store
