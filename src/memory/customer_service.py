"""客服消息与人工接管持久化。"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import func, select, update

from src.memory.db import (
    conversation_metadata_table,
    customer_service_messages_table,
    ensure_managed_schema,
    get_async_engine,
    human_handoffs_table,
)

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


def _sender_type_to_unified_role(sender_type: str) -> str | None:
    mapping = {
        "customer": "user",
        "ai": "assistant",
        "human": "human",
        "system": "system",
    }
    return mapping.get(sender_type)


def _handoff_returning():
    return (
        human_handoffs_table.c.id,
        human_handoffs_table.c.thread_id,
        human_handoffs_table.c.user_id,
        human_handoffs_table.c.channel,
        human_handoffs_table.c.status,
        human_handoffs_table.c.reason,
        human_handoffs_table.c.last_customer_message,
        human_handoffs_table.c.claimed_by,
        human_handoffs_table.c.claimed_at,
        human_handoffs_table.c.resolved_at,
        human_handoffs_table.c.created_at,
        human_handoffs_table.c.updated_at,
    )


class CustomerServiceStore:
    """客服消息与人工接管存储。"""

    def __init__(self):
        self._engine = None
        self._disabled_reason: str | None = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("客服存储已降级", reason=reason, error=error)
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

    async def append_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        channel: str,
        sender_type: str,
        content: str,
    ) -> dict | None:
        row = await self._write_fetchrow(
            customer_service_messages_table.insert()
            .values(
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
                sender_type=sender_type,
                content=content,
            )
            .returning(
                customer_service_messages_table.c.id,
                customer_service_messages_table.c.thread_id,
                customer_service_messages_table.c.user_id,
                customer_service_messages_table.c.channel,
                customer_service_messages_table.c.sender_type,
                customer_service_messages_table.c.content,
                customer_service_messages_table.c.created_at,
            )
        )
        unified_role = _sender_type_to_unified_role(sender_type)
        if unified_role:
            from src.memory.conversations import get_conversation_store

            conversation_store = get_conversation_store()
            await conversation_store.record_messages(
                thread_id=thread_id,
                user_id=user_id,
                user_role="customer",
                channel=channel,
                store_id=None,
                messages=[{"role": unified_role, "content": content}],
            )
        return _row_to_message(row)

    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        conditions = [customer_service_messages_table.c.thread_id == thread_id]
        if user_id is not None:
            conditions.append(customer_service_messages_table.c.user_id == user_id)
        rows = await self._fetch(
            select(
                customer_service_messages_table.c.id,
                customer_service_messages_table.c.thread_id,
                customer_service_messages_table.c.user_id,
                customer_service_messages_table.c.channel,
                customer_service_messages_table.c.sender_type,
                customer_service_messages_table.c.content,
                customer_service_messages_table.c.created_at,
            )
            .where(*conditions)
            .order_by(customer_service_messages_table.c.created_at.asc())
            .limit(limit)
        )
        return [_row_to_message(row) for row in rows]

    async def is_customer_thread(self, thread_id: str, *, user_id: str | None = None) -> bool:
        conditions = [customer_service_messages_table.c.thread_id == thread_id]
        if user_id is not None:
            conditions.append(customer_service_messages_table.c.user_id == user_id)
        message_row = await self._fetchrow(
            select(customer_service_messages_table.c.id).where(*conditions).limit(1)
        )
        if message_row:
            return True

        metadata_conditions = [
            conversation_metadata_table.c.thread_id == thread_id,
            conversation_metadata_table.c.user_role == "customer",
        ]
        if user_id is not None:
            metadata_conditions.append(conversation_metadata_table.c.user_id == user_id)
        metadata_row = await self._fetchrow(
            select(conversation_metadata_table.c.thread_id).where(*metadata_conditions).limit(1)
        )
        return bool(metadata_row)

    async def get_active_handoff(self, thread_id: str) -> dict | None:
        row = await self._fetchrow(
            select(*_handoff_returning())
            .where(
                human_handoffs_table.c.thread_id == thread_id,
                human_handoffs_table.c.status.in_(("pending", "claimed")),
            )
            .order_by(human_handoffs_table.c.updated_at.desc())
            .limit(1)
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
            row = await self._write_fetchrow(
                update(human_handoffs_table)
                .where(human_handoffs_table.c.id == active["id"])
                .values(
                    reason=reason,
                    last_customer_message=last_customer_message,
                    updated_at=func.now(),
                )
                .returning(*_handoff_returning())
            )
            return _row_to_handoff(row)

        row = await self._write_fetchrow(
            human_handoffs_table.insert()
            .values(
                id=f"handoff_{thread_id}",
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
                status="pending",
                reason=reason,
                last_customer_message=last_customer_message,
            )
            .returning(*_handoff_returning())
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
        conditions = []
        if status:
            conditions.append(human_handoffs_table.c.status == status)
        if channel:
            conditions.append(human_handoffs_table.c.channel == channel)
        rows = await self._fetch(
            select(*_handoff_returning())
            .where(*conditions)
            .order_by(human_handoffs_table.c.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_row = await self._fetchrow(
            select(func.count().label("total")).select_from(human_handoffs_table).where(*conditions)
        )
        return {
            "items": [_row_to_handoff(row) for row in rows],
            "total": int(count_row["total"]) if count_row else 0,
        }

    async def get_handoff_detail(self, handoff_id: str) -> dict | None:
        row = await self._fetchrow(
            select(*_handoff_returning()).where(human_handoffs_table.c.id == handoff_id)
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
        row = await self._write_fetchrow(
            update(human_handoffs_table)
            .where(
                human_handoffs_table.c.id == handoff_id,
                human_handoffs_table.c.status.in_(("pending", "claimed")),
            )
            .values(
                status="claimed",
                claimed_by=agent_id,
                claimed_at=func.coalesce(human_handoffs_table.c.claimed_at, func.now()),
                updated_at=func.now(),
            )
            .returning(*_handoff_returning())
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

        row = await self._write_fetchrow(
            update(human_handoffs_table)
            .where(human_handoffs_table.c.id == handoff_id)
            .values(updated_at=func.now())
            .returning(*_handoff_returning())
        )
        return _row_to_handoff(row)

    async def resolve_handoff(
        self,
        *,
        handoff_id: str,
        agent_id: str,
        resolution_note: str,
    ) -> dict | None:
        row = await self._write_fetchrow(
            update(human_handoffs_table)
            .where(
                human_handoffs_table.c.id == handoff_id,
                human_handoffs_table.c.status.in_(("pending", "claimed")),
            )
            .values(
                status="resolved",
                claimed_by=func.coalesce(human_handoffs_table.c.claimed_by, agent_id),
                claimed_at=func.coalesce(human_handoffs_table.c.claimed_at, func.now()),
                resolved_at=func.now(),
                updated_at=func.now(),
            )
            .returning(*_handoff_returning())
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
        self._engine = None


_customer_service_store: CustomerServiceStore | None = None


def get_customer_service_store() -> CustomerServiceStore:
    global _customer_service_store
    if _customer_service_store is None:
        _customer_service_store = CustomerServiceStore()
    return _customer_service_store
