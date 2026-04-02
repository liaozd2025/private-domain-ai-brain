"""会话持久化 - LangGraph PostgresSaver 封装

使用 PostgreSQL 作为会话 checkpointer，支持：
  - 多轮对话历史持久化
  - 断线续聊（thread_id 恢复）
  - 并发安全的状态读写
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from src.config import settings

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = structlog.get_logger(__name__)

_checkpointer: AsyncPostgresSaver | None = None
_conn_pool = None
_checkpointer_lock = asyncio.Lock()


async def init_checkpointer() -> AsyncPostgresSaver:
    """初始化 checkpointer 和数据库表"""
    global _checkpointer, _conn_pool

    try:
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        logger.info("初始化 PostgreSQL checkpointer...")

        # 创建连接池
        _conn_pool = AsyncConnectionPool(
            conninfo=settings.database_url_sync,
            max_size=20,
            kwargs={"autocommit": True, "row_factory": psycopg.rows.dict_row},
        )
        await _conn_pool.open()

        # 创建 checkpointer
        _checkpointer = AsyncPostgresSaver(_conn_pool)

        # 自动创建 LangGraph 所需的表
        await _checkpointer.setup()

        logger.info("PostgreSQL checkpointer 初始化完成")
        return _checkpointer
    except Exception:
        _checkpointer = None
        _conn_pool = None
        raise


async def get_checkpointer() -> AsyncPostgresSaver:
    """获取 checkpointer 实例（并发安全）"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    async with _checkpointer_lock:
        if _checkpointer is None:
            await init_checkpointer()
    return _checkpointer


async def close_checkpointer():
    """关闭连接池"""
    global _conn_pool, _checkpointer
    if _conn_pool:
        await _conn_pool.close()
        logger.info("数据库连接池已关闭")
    _checkpointer = None
    _conn_pool = None
