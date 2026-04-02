"""统一会话元数据与消息明细持久化。"""

from __future__ import annotations

import base64
import inspect
import json
import re
from datetime import datetime

import structlog
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.memory.db import (
    conversation_messages_table,
    conversation_metadata_table,
    ensure_managed_schema,
    get_async_engine,
)

logger = structlog.get_logger(__name__)

UNIFIED_MESSAGE_SOURCE = "unified"
LEGACY_MESSAGE_SOURCE = "legacy"


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


def _parse_cursor_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_summary(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "thread_id": row["thread_id"],
        "user_id": row.get("user_id"),
        "user_role": row.get("user_role") or "unknown",
        "title": row.get("title") or "新会话",
        "channel": row.get("channel") or "web",
        "created_at": _serialize_timestamp(row.get("created_at")),
        "last_message_at": _serialize_timestamp(row.get("last_message_at")),
        "message_count": row.get("message_count", 0),
        "message_source": row.get("message_source") or LEGACY_MESSAGE_SOURCE,
        "is_deleted": bool(row.get("is_deleted", False)),
        "deleted_at": _serialize_timestamp(row.get("deleted_at")),
    }


def _row_to_message(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "role": row["role"],
        "content": row["content"],
        "created_at": _serialize_timestamp(row.get("created_at")),
    }


def _encode_cursor(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_cursor(cursor: str | None) -> dict[str, str] | None:
    if not cursor:
        return None
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}".encode()).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError("无效的游标") from exc
    if not isinstance(payload, dict):
        raise ValueError("无效的游标")
    return {str(key): str(value) for key, value in payload.items()}


def _summary_cursor(item: dict | None) -> str | None:
    if not item or not item.get("last_message_at"):
        return None
    return _encode_cursor(
        {
            "last_message_at": str(item["last_message_at"]),
            "thread_id": str(item["thread_id"]),
        }
    )


def _message_cursor(item: dict | None) -> str | None:
    if not item or not item.get("created_at"):
        return None
    return _encode_cursor(
        {
            "created_at": str(item["created_at"]),
            "id": str(item["id"]),
        }
    )


def _returning_summary():
    return (
        conversation_metadata_table.c.thread_id,
        conversation_metadata_table.c.user_id,
        conversation_metadata_table.c.user_role,
        conversation_metadata_table.c.title,
        conversation_metadata_table.c.channel,
        conversation_metadata_table.c.created_at,
        conversation_metadata_table.c.last_message_at,
        conversation_metadata_table.c.message_count,
        conversation_metadata_table.c.message_source,
        conversation_metadata_table.c.is_deleted,
        conversation_metadata_table.c.deleted_at,
    )


class ConversationStore:
    """统一会话存储。"""

    def __init__(self):
        self._engine = None
        self._disabled_reason: str | None = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("会话存储已降级", reason=reason, error=error)
            self._logged_disabled_reason = True

    def _get_engine(self):
        if self._disabled_reason:
            return None
        if self._engine is None:
            try:
                self._engine = get_async_engine()
            except Exception as exc:
                self._disable("engine_init_failed", error=str(exc))
                return None
        return self._engine

    async def _ensure_schema(self) -> bool:
        engine = self._get_engine()
        if engine is None:
            return False
        try:
            await ensure_managed_schema()
        except Exception as exc:
            self._disable("schema_init_failed", error=str(exc))
            return False
        return True

    async def _fetchrow(self, stmt):
        if not await self._ensure_schema():
            return None
        engine = self._get_engine()
        if engine is None:
            return None
        async with engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def _write_fetchrow(self, stmt):
        if not await self._ensure_schema():
            return None
        engine = self._get_engine()
        if engine is None:
            return None
        async with engine.begin() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def _fetch(self, stmt):
        if not await self._ensure_schema():
            return []
        engine = self._get_engine()
        if engine is None:
            return []
        async with engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(row) for row in rows]

    async def _execute(self, stmt):
        if not await self._ensure_schema():
            return 0
        engine = self._get_engine()
        if engine is None:
            return 0
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
        return result.rowcount or 0

    async def record_messages(
        self,
        *,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        channel: str,
        store_id: str | None = None,
        messages: list[dict[str, str]],
    ) -> dict:
        normalized_messages = []
        for item in messages:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if not role or not content:
                continue
            normalized_messages.append({"role": role, "content": content})
        if not normalized_messages:
            return {}

        if not await self._ensure_schema():
            return {}
        engine = self._get_engine()
        if engine is None:
            return {}

        title_source = next(
            (item["content"] for item in normalized_messages if item["role"] == "user"),
            normalized_messages[0]["content"],
        )
        insert_stmt = pg_insert(conversation_metadata_table).values(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            title=build_conversation_title(title_source),
            channel=channel,
            message_count=len(normalized_messages),
            message_source=UNIFIED_MESSAGE_SOURCE,
            is_deleted=False,
            deleted_at=None,
        )
        meta_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[conversation_metadata_table.c.thread_id],
            set_={
                "user_id": insert_stmt.excluded.user_id,
                "user_role": insert_stmt.excluded.user_role,
                "channel": insert_stmt.excluded.channel,
                "last_message_at": func.now(),
                "message_count": (
                    conversation_metadata_table.c.message_count
                    + insert_stmt.excluded.message_count
                ),
                "message_source": UNIFIED_MESSAGE_SOURCE,
                "is_deleted": False,
                "deleted_at": None,
                "title": case(
                    (
                        or_(
                            conversation_metadata_table.c.title.is_(None),
                            conversation_metadata_table.c.title == "",
                        ),
                        insert_stmt.excluded.title,
                    ),
                    else_=conversation_metadata_table.c.title,
                ),
            },
        ).returning(*_returning_summary())

        async with engine.begin() as conn:
            for item in normalized_messages:
                await conn.execute(
                    conversation_messages_table.insert().values(
                        thread_id=thread_id,
                        user_id=user_id,
                        channel=channel,
                        store_id=store_id,
                        role=item["role"],
                        content=item["content"],
                    )
                )
            row = (await conn.execute(meta_stmt)).mappings().first()

        return _row_to_summary(dict(row) if row else None) or {}

    async def save_user_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        message: str,
        channel: str,
        store_id: str | None = None,
    ) -> None:
        """请求到达时立即落库用户消息，同时 upsert 会话元数据。原子事务。"""
        if not message.strip():
            return
        if not await self._ensure_schema():
            return
        engine = self._get_engine()
        if engine is None:
            return

        insert_stmt = pg_insert(conversation_metadata_table).values(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            title=build_conversation_title(message),
            channel=channel,
            message_count=1,
            message_source=UNIFIED_MESSAGE_SOURCE,
            is_deleted=False,
            deleted_at=None,
        )
        meta_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[conversation_metadata_table.c.thread_id],
            set_={
                "user_id": insert_stmt.excluded.user_id,
                "user_role": insert_stmt.excluded.user_role,
                "channel": insert_stmt.excluded.channel,
                "last_message_at": func.now(),
                "message_count": conversation_metadata_table.c.message_count + 1,
                "message_source": UNIFIED_MESSAGE_SOURCE,
                "is_deleted": False,
                "deleted_at": None,
                "title": case(
                    (
                        or_(
                            conversation_metadata_table.c.title.is_(None),
                            conversation_metadata_table.c.title == "",
                        ),
                        insert_stmt.excluded.title,
                    ),
                    else_=conversation_metadata_table.c.title,
                ),
            },
        )
        async with engine.begin() as conn:
            await conn.execute(
                conversation_messages_table.insert().values(
                    thread_id=thread_id,
                    user_id=user_id,
                    channel=channel,
                    store_id=store_id,
                    role="user",
                    content=message,
                )
            )
            await conn.execute(meta_stmt)

    async def save_assistant_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        channel: str,
        store_id: str | None = None,
        content: str,
    ) -> None:
        """AI 回复完成后落库 assistant 消息，同时更新元数据计数。原子事务。"""
        if not content.strip():
            return
        if not await self._ensure_schema():
            return
        engine = self._get_engine()
        if engine is None:
            return

        async with engine.begin() as conn:
            await conn.execute(
                conversation_messages_table.insert().values(
                    thread_id=thread_id,
                    user_id=user_id,
                    channel=channel,
                    store_id=store_id,
                    role="assistant",
                    content=content,
                )
            )
            await conn.execute(
                update(conversation_metadata_table)
                .where(conversation_metadata_table.c.thread_id == thread_id)
                .values(
                    message_count=conversation_metadata_table.c.message_count + 1,
                    last_message_at=func.now(),
                )
            )

    async def upsert_on_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        message: str,
        channel: str,
        increment: int = 2,
    ) -> dict:
        """兼容旧调用，仅更新会话索引。"""
        insert_stmt = pg_insert(conversation_metadata_table).values(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            title=build_conversation_title(message),
            channel=channel,
            message_count=increment,
            message_source=LEGACY_MESSAGE_SOURCE,
            is_deleted=False,
            deleted_at=None,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[conversation_metadata_table.c.thread_id],
            set_={
                "user_id": insert_stmt.excluded.user_id,
                "user_role": insert_stmt.excluded.user_role,
                "channel": insert_stmt.excluded.channel,
                "last_message_at": func.now(),
                "message_count": (
                    conversation_metadata_table.c.message_count
                    + insert_stmt.excluded.message_count
                ),
                "is_deleted": False,
                "deleted_at": None,
                "title": case(
                    (
                        or_(
                            conversation_metadata_table.c.title.is_(None),
                            conversation_metadata_table.c.title == "",
                        ),
                        insert_stmt.excluded.title,
                    ),
                    else_=conversation_metadata_table.c.title,
                ),
            },
        ).returning(*_returning_summary())
        row = await self._write_fetchrow(stmt)
        return _row_to_summary(row) or {}

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 20,
        before: str | None = None,
        after: str | None = None,
    ) -> dict:
        if before and after:
            raise ValueError("before 和 after 不能同时传入")

        safe_limit = max(1, min(limit, 100))
        conditions = [
            conversation_metadata_table.c.user_id == user_id,
            conversation_metadata_table.c.is_deleted.is_(False),
            conversation_metadata_table.c.message_source == UNIFIED_MESSAGE_SOURCE,
        ]
        order_by = [
            conversation_metadata_table.c.last_message_at.desc(),
            conversation_metadata_table.c.thread_id.desc(),
        ]

        if before:
            cursor = _decode_cursor(before)
            cursor_ts = _parse_cursor_timestamp(cursor["last_message_at"])
            conditions.append(
                or_(
                    conversation_metadata_table.c.last_message_at < cursor_ts,
                    and_(
                        conversation_metadata_table.c.last_message_at == cursor_ts,
                        conversation_metadata_table.c.thread_id < cursor["thread_id"],
                    ),
                )
            )
        elif after:
            cursor = _decode_cursor(after)
            cursor_ts = _parse_cursor_timestamp(cursor["last_message_at"])
            conditions.append(
                or_(
                    conversation_metadata_table.c.last_message_at > cursor_ts,
                    and_(
                        conversation_metadata_table.c.last_message_at == cursor_ts,
                        conversation_metadata_table.c.thread_id > cursor["thread_id"],
                    ),
                )
            )
            order_by = [
                conversation_metadata_table.c.last_message_at.asc(),
                conversation_metadata_table.c.thread_id.asc(),
            ]

        stmt = (
            select(*_returning_summary())
            .where(*conditions)
            .order_by(*order_by)
            .limit(safe_limit)
        )
        items = [_row_to_summary(row) for row in await self._fetch(stmt)]
        if after:
            items.reverse()

        count_row = await self._fetchrow(
            select(func.count().label("total"))
            .select_from(conversation_metadata_table)
            .where(
                conversation_metadata_table.c.user_id == user_id,
                conversation_metadata_table.c.is_deleted.is_(False),
                conversation_metadata_table.c.message_source == UNIFIED_MESSAGE_SOURCE,
            )
        )

        has_more_older = False
        has_more_newer = False
        if items:
            last_item = items[-1]
            first_item = items[0]
            last_ts = _parse_cursor_timestamp(last_item["last_message_at"])
            first_ts = _parse_cursor_timestamp(first_item["last_message_at"])
            older_probe = await self._fetch(
                select(conversation_metadata_table.c.thread_id)
                .where(
                    conversation_metadata_table.c.user_id == user_id,
                    conversation_metadata_table.c.is_deleted.is_(False),
                    conversation_metadata_table.c.message_source == UNIFIED_MESSAGE_SOURCE,
                    or_(
                        conversation_metadata_table.c.last_message_at < last_ts,
                        and_(
                            conversation_metadata_table.c.last_message_at == last_ts,
                            conversation_metadata_table.c.thread_id < last_item["thread_id"],
                        ),
                    ),
                )
                .order_by(
                    conversation_metadata_table.c.last_message_at.desc(),
                    conversation_metadata_table.c.thread_id.desc(),
                )
                .limit(1)
            )
            newer_probe = await self._fetch(
                select(conversation_metadata_table.c.thread_id)
                .where(
                    conversation_metadata_table.c.user_id == user_id,
                    conversation_metadata_table.c.is_deleted.is_(False),
                    conversation_metadata_table.c.message_source == UNIFIED_MESSAGE_SOURCE,
                    or_(
                        conversation_metadata_table.c.last_message_at > first_ts,
                        and_(
                            conversation_metadata_table.c.last_message_at == first_ts,
                            conversation_metadata_table.c.thread_id > first_item["thread_id"],
                        ),
                    ),
                )
                .order_by(
                    conversation_metadata_table.c.last_message_at.asc(),
                    conversation_metadata_table.c.thread_id.asc(),
                )
                .limit(1)
            )
            has_more_older = bool(older_probe)
            has_more_newer = bool(newer_probe)

        return {
            "items": items,
            "total": int(count_row["total"]) if count_row else 0,
            "paging": {
                "older_cursor": _summary_cursor(items[-1]) if items else None,
                "newer_cursor": _summary_cursor(items[0]) if items else None,
                "has_more_older": has_more_older,
                "has_more_newer": has_more_newer,
            },
        }

    async def get_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        include_deleted: bool = False,
    ) -> dict | None:
        conditions = [conversation_metadata_table.c.thread_id == thread_id]
        if user_id is not None:
            conditions.append(conversation_metadata_table.c.user_id == user_id)
        if not include_deleted:
            conditions.append(conversation_metadata_table.c.is_deleted.is_(False))
        row = await self._fetchrow(select(*_returning_summary()).where(*conditions))
        return _row_to_summary(row)

    async def list_messages(
        self,
        *,
        thread_id: str,
        user_id: str | None = None,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> dict:
        if before and after:
            raise ValueError("before 和 after 不能同时传入")

        safe_limit = max(1, min(limit, 200))
        conditions = [conversation_messages_table.c.thread_id == thread_id]
        if user_id is not None:
            conditions.append(conversation_messages_table.c.user_id == user_id)
        order_by = [
            conversation_messages_table.c.created_at.desc(),
            conversation_messages_table.c.id.desc(),
        ]

        if before:
            cursor = _decode_cursor(before)
            cursor_ts = _parse_cursor_timestamp(cursor["created_at"])
            cursor_id = int(cursor["id"])
            conditions.append(
                or_(
                    conversation_messages_table.c.created_at < cursor_ts,
                    and_(
                        conversation_messages_table.c.created_at == cursor_ts,
                        conversation_messages_table.c.id < cursor_id,
                    ),
                )
            )
        elif after:
            cursor = _decode_cursor(after)
            cursor_ts = _parse_cursor_timestamp(cursor["created_at"])
            cursor_id = int(cursor["id"])
            conditions.append(
                or_(
                    conversation_messages_table.c.created_at > cursor_ts,
                    and_(
                        conversation_messages_table.c.created_at == cursor_ts,
                        conversation_messages_table.c.id > cursor_id,
                    ),
                )
            )
            order_by = [
                conversation_messages_table.c.created_at.asc(),
                conversation_messages_table.c.id.asc(),
            ]

        stmt = (
            select(
                conversation_messages_table.c.id,
                conversation_messages_table.c.role,
                conversation_messages_table.c.content,
                conversation_messages_table.c.created_at,
            )
            .where(*conditions)
            .order_by(*order_by)
            .limit(safe_limit)
        )
        items = [_row_to_message(row) for row in await self._fetch(stmt)]
        if not after:
            items.reverse()

        count_conditions = [conversation_messages_table.c.thread_id == thread_id]
        if user_id is not None:
            count_conditions.append(conversation_messages_table.c.user_id == user_id)
        count_row = await self._fetchrow(
            select(func.count().label("total"))
            .select_from(conversation_messages_table)
            .where(*count_conditions)
        )

        has_more_older = False
        has_more_newer = False
        if items:
            first_item = items[0]
            last_item = items[-1]
            first_ts = _parse_cursor_timestamp(first_item["created_at"])
            last_ts = _parse_cursor_timestamp(last_item["created_at"])
            first_id = int(first_item["id"])
            last_id = int(last_item["id"])

            older_conditions = list(count_conditions)
            older_conditions.append(
                or_(
                    conversation_messages_table.c.created_at < first_ts,
                    and_(
                        conversation_messages_table.c.created_at == first_ts,
                        conversation_messages_table.c.id < first_id,
                    ),
                )
            )
            newer_conditions = list(count_conditions)
            newer_conditions.append(
                or_(
                    conversation_messages_table.c.created_at > last_ts,
                    and_(
                        conversation_messages_table.c.created_at == last_ts,
                        conversation_messages_table.c.id > last_id,
                    ),
                )
            )

            older_probe = await self._fetch(
                select(conversation_messages_table.c.id)
                .where(*older_conditions)
                .order_by(
                    conversation_messages_table.c.created_at.desc(),
                    conversation_messages_table.c.id.desc(),
                )
                .limit(1)
            )
            newer_probe = await self._fetch(
                select(conversation_messages_table.c.id)
                .where(*newer_conditions)
                .order_by(
                    conversation_messages_table.c.created_at.asc(),
                    conversation_messages_table.c.id.asc(),
                )
                .limit(1)
            )
            has_more_older = bool(older_probe)
            has_more_newer = bool(newer_probe)

        return {
            "items": items,
            "total": int(count_row["total"]) if count_row else 0,
            "paging": {
                "older_cursor": _message_cursor(items[0]) if items else None,
                "newer_cursor": _message_cursor(items[-1]) if items else None,
                "has_more_older": has_more_older,
                "has_more_newer": has_more_newer,
            },
        }

    async def rename(self, thread_id: str, user_id: str, title: str) -> dict | None:
        row = await self._write_fetchrow(
            update(conversation_metadata_table)
            .where(
                conversation_metadata_table.c.thread_id == thread_id,
                conversation_metadata_table.c.user_id == user_id,
                conversation_metadata_table.c.is_deleted.is_(False),
            )
            .values(title=title.strip())
            .returning(*_returning_summary())
        )
        return _row_to_summary(row)

    async def soft_delete(self, thread_id: str, user_id: str) -> bool:
        rowcount = await self._execute(
            update(conversation_metadata_table)
            .where(
                conversation_metadata_table.c.thread_id == thread_id,
                conversation_metadata_table.c.user_id == user_id,
                conversation_metadata_table.c.is_deleted.is_(False),
            )
            .values(is_deleted=True, deleted_at=func.now())
        )
        return rowcount > 0

    async def close(self):
        self._engine = None


async def record_conversation_turn(
    *,
    thread_id: str,
    user_id: str,
    user_role: str = "unknown",
    message: str | None = None,
    assistant_message: str | None = None,
    channel: str,
    store_id: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> None:
    """记录一次成功完成的对话。"""
    if not user_id or not thread_id:
        return

    normalized_messages = list(messages or [])
    if not normalized_messages and message:
        normalized_messages.append({"role": "user", "content": message})
        if assistant_message:
            normalized_messages.append({"role": "assistant", "content": assistant_message})

    try:
        store = get_conversation_store()
        record_messages = getattr(store, "record_messages", None)
        if inspect.iscoroutinefunction(record_messages):
            await record_messages(
                thread_id=thread_id,
                user_id=user_id,
                user_role=user_role,
                channel=channel,
                store_id=store_id,
                messages=normalized_messages,
            )
        else:
            await store.upsert_on_turn(
                thread_id=thread_id,
                user_id=user_id,
                user_role=user_role,
                message=message or "",
                channel=channel,
            )
    except Exception as exc:
        logger.warning(
            "记录会话元数据失败",
            thread_id=thread_id,
            user_id=user_id,
            error=str(exc),
        )


_conversation_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store
