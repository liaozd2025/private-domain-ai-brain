"""用户画像持久化 - SQLAlchemy Async Core。"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.memory.db import ensure_managed_schema, get_async_engine, user_profiles_table

logger = structlog.get_logger(__name__)


def _decode_json_field(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        import json

        return json.loads(value)
    except Exception:
        return default


class UserProfileStore:
    """用户画像存储。"""

    def __init__(self):
        self._engine = None
        self._disabled_reason: str | None = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        """禁用存储能力，避免重复初始化和重复报错。"""
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("用户画像存储已降级", reason=reason, error=error)
            self._logged_disabled_reason = True

    def _get_engine(self):
        """获取共享 async engine。"""
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

    async def get_profile(self, user_id: str) -> dict:
        """获取用户画像。"""
        if not user_id:
            return {}

        try:
            if not await self._ensure_schema():
                return {}
            engine = self._get_engine()
            if engine is None:
                return {}
            stmt = (
                select(
                    user_profiles_table.c.role,
                    user_profiles_table.c.preferences,
                    user_profiles_table.c.topics,
                )
                .where(user_profiles_table.c.user_id == user_id)
            )
            async with engine.connect() as conn:
                row = (await conn.execute(stmt)).mappings().first()
            if not row:
                return {}
            return {
                "role": row["role"],
                "preferences": _decode_json_field(row["preferences"], {}),
                "topics": _decode_json_field(row["topics"], []),
            }
        except Exception as exc:
            logger.warning("获取用户画像失败", user_id=user_id, error=str(exc))
            return {}

    async def update_profile(self, user_id: str, updates: dict) -> bool:
        """更新用户画像（UPSERT）。"""
        if not user_id:
            return False

        try:
            if not await self._ensure_schema():
                return False
            engine = self._get_engine()
            if engine is None:
                return False

            existing = await self.get_profile(user_id)
            role = updates.get("role", existing.get("role", "unknown"))
            preferences = {**existing.get("preferences", {}), **updates.get("preferences", {})}
            topics = list(existing.get("topics", []))
            for topic in updates.get("topics", []):
                if topic not in topics:
                    topics.append(topic)
            topics = topics[-20:]

            insert_stmt = pg_insert(user_profiles_table).values(
                user_id=user_id,
                role=role,
                preferences=preferences,
                topics=topics,
            )
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=[user_profiles_table.c.user_id],
                set_={
                    "role": role,
                    "preferences": preferences,
                    "topics": topics,
                    "updated_at": func.now(),
                },
            )
            async with engine.begin() as conn:
                await conn.execute(stmt)

            logger.debug("用户画像已更新", user_id=user_id, role=role)
            return True
        except Exception as exc:
            logger.error("更新用户画像失败", user_id=user_id, error=str(exc))
            return False

    async def close(self):
        """共享 engine 由应用生命周期统一关闭。"""
        self._engine = None


_profile_store: UserProfileStore | None = None


def get_profile_store() -> UserProfileStore:
    """获取全局用户画像存储实例。"""
    global _profile_store
    if _profile_store is None:
        _profile_store = UserProfileStore()
    return _profile_store
