"""用户画像持久化 - PostgreSQL 存储

功能：
  - 读取/写入用户角色、偏好、历史话题
  - 使用 namespace 隔离不同用户数据
  - 异步非阻塞操作
"""

import json
from typing import Optional

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class UserProfileStore:
    """用户画像存储，直接操作 PostgreSQL"""

    def __init__(self):
        self._pool = None
        self._disabled_reason: Optional[str] = None
        self._logged_disabled_reason = False

    def _disable(self, reason: str, *, error: str = "") -> None:
        """禁用存储能力，避免重复初始化和重复报错"""
        self._disabled_reason = reason
        if not self._logged_disabled_reason:
            logger.warning("用户画像存储已降级", reason=reason, error=error)
            self._logged_disabled_reason = True

    async def _get_pool(self):
        """获取数据库连接池（懒加载）"""
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
        return self._pool

    async def get_profile(self, user_id: str) -> dict:
        """获取用户画像

        Args:
            user_id: 用户 ID

        Returns:
            用户画像字典，包含 role/preferences/topics
        """
        if not user_id:
            return {}

        try:
            pool = await self._get_pool()
            if pool is None:
                return {}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT role, preferences, topics FROM user_profiles WHERE user_id = $1",
                    user_id,
                )
                if not row:
                    return {}

                return {
                    "role": row["role"],
                    "preferences": json.loads(row["preferences"]) if row["preferences"] else {},
                    "topics": json.loads(row["topics"]) if row["topics"] else [],
                }
        except Exception as e:
            logger.warning("获取用户画像失败", user_id=user_id, error=str(e))
            return {}

    async def update_profile(self, user_id: str, updates: dict) -> bool:
        """更新用户画像（UPSERT）

        Args:
            user_id: 用户 ID
            updates: 要更新的字段，支持 role/preferences/topics

        Returns:
            是否更新成功
        """
        if not user_id:
            return False

        try:
            pool = await self._get_pool()
            if pool is None:
                return False
            async with pool.acquire() as conn:
                # 获取现有画像
                existing = await self.get_profile(user_id)

                # 合并更新
                role = updates.get("role", existing.get("role", "unknown"))
                preferences = {**existing.get("preferences", {}), **updates.get("preferences", {})}
                topics = existing.get("topics", [])

                # 新话题追加（去重，保留最近 20 个）
                new_topics = updates.get("topics", [])
                for topic in new_topics:
                    if topic not in topics:
                        topics.append(topic)
                topics = topics[-20:]  # 只保留最近 20 个

                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, role, preferences, topics)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id) DO UPDATE
                    SET role = $2,
                        preferences = $3,
                        topics = $4,
                        updated_at = NOW()
                    """,
                    user_id,
                    role,
                    json.dumps(preferences, ensure_ascii=False),
                    json.dumps(topics, ensure_ascii=False),
                )

                logger.debug("用户画像已更新", user_id=user_id, role=role)
                return True

        except Exception as e:
            logger.error("更新用户画像失败", user_id=user_id, error=str(e))
            return False

    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()


# 全局单例
_profile_store: Optional[UserProfileStore] = None


def get_profile_store() -> UserProfileStore:
    """获取全局用户画像存储实例"""
    global _profile_store
    if _profile_store is None:
        _profile_store = UserProfileStore()
    return _profile_store
