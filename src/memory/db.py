"""共享 SQLAlchemy Async Core 数据库层。"""

from __future__ import annotations

import asyncio

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.config import settings

metadata = MetaData()

user_profiles_table = Table(
    "user_profiles",
    metadata,
    Column("user_id", String(255), primary_key=True),
    Column("role", String(50), nullable=False, server_default=text("'unknown'")),
    Column("preferences", JSON, nullable=False, server_default=text("'{}'")),
    Column("topics", JSON, nullable=False, server_default=text("'[]'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

conversation_metadata_table = Table(
    "conversation_metadata",
    metadata,
    Column("thread_id", String(255), primary_key=True),
    Column("user_id", String(255)),
    Column("user_role", String(50), nullable=False, server_default=text("'unknown'")),
    Column("title", String(500)),
    Column("channel", String(50), nullable=False, server_default=text("'web'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_message_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("message_count", Integer, nullable=False, server_default=text("0")),
    Column("message_source", String(20), nullable=False, server_default=text("'legacy'")),
    Column("is_deleted", Boolean, nullable=False, server_default=text("FALSE")),
    Column("deleted_at", DateTime(timezone=True)),
)

conversation_messages_table = Table(
    "conversation_messages",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("thread_id", String(255), nullable=False),
    Column("user_id", String(255), nullable=False),
    Column("channel", String(50), nullable=False, server_default=text("'web'")),
    Column("store_id", String(255)),
    Column("role", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

customer_service_messages_table = Table(
    "customer_service_messages",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("thread_id", String(255), nullable=False),
    Column("user_id", String(255), nullable=False),
    Column("channel", String(50), nullable=False, server_default=text("'web'")),
    Column("sender_type", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

human_handoffs_table = Table(
    "human_handoffs",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("thread_id", String(255), nullable=False),
    Column("user_id", String(255), nullable=False),
    Column("channel", String(50), nullable=False, server_default=text("'web'")),
    Column("status", String(20), nullable=False),
    Column("reason", Text),
    Column("last_customer_message", Text),
    Column("claimed_by", String(255)),
    Column("claimed_at", DateTime(timezone=True)),
    Column("resolved_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index(
    "idx_conv_meta_user_active",
    conversation_metadata_table.c.user_id,
    conversation_metadata_table.c.is_deleted,
    conversation_metadata_table.c.message_source,
    conversation_metadata_table.c.last_message_at.desc(),
)
Index(
    "idx_conversation_messages_thread_desc",
    conversation_messages_table.c.thread_id,
    conversation_messages_table.c.created_at.desc(),
    conversation_messages_table.c.id.desc(),
)
Index(
    "idx_conversation_messages_thread_asc",
    conversation_messages_table.c.thread_id,
    conversation_messages_table.c.created_at.asc(),
    conversation_messages_table.c.id.asc(),
)
Index(
    "idx_customer_service_messages_thread",
    customer_service_messages_table.c.thread_id,
    customer_service_messages_table.c.created_at.asc(),
)
Index(
    "idx_human_handoffs_status",
    human_handoffs_table.c.status,
    human_handoffs_table.c.updated_at.desc(),
)
Index(
    "idx_human_handoffs_thread",
    human_handoffs_table.c.thread_id,
    human_handoffs_table.c.updated_at.desc(),
)

uploaded_files_table = Table(
    "uploaded_files",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("file_id", String(64), nullable=False, unique=True),
    Column("thread_id", String(255)),
    Column("user_id", String(255)),
    Column("filename", String(500)),
    Column("file_path", Text),
    Column("file_type", String(50)),
    Column("file_size_bytes", Integer),
    Column("uploaded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("idx_files_thread", uploaded_files_table.c.thread_id)
Index("idx_files_user", uploaded_files_table.c.user_id)

api_credentials_table = Table(
    "api_credentials",
    metadata,
    Column("app_id", String(64), primary_key=True),
    Column("secret_hash", String(128), nullable=False),
    Column("app_name", String(255), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("TRUE")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index(
    "idx_api_credentials_active",
    api_credentials_table.c.app_id,
    postgresql_where=api_credentials_table.c.is_active.is_(True),
)

_async_engine: AsyncEngine | None = None
_schema_ready = False
_schema_lock = asyncio.Lock()


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            settings.database_url_async,
            pool_pre_ping=True,
        )
    return _async_engine


async def ensure_managed_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    async with _schema_lock:
        if _schema_ready:
            return
        engine = get_async_engine()
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.execute(
                text(
                    "ALTER TABLE conversation_metadata "
                    "ADD COLUMN IF NOT EXISTS user_role VARCHAR(50) DEFAULT 'unknown'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE conversation_metadata "
                    "ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE conversation_metadata "
                    "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE conversation_metadata "
                    "ADD COLUMN IF NOT EXISTS message_source VARCHAR(20) NOT NULL DEFAULT 'legacy'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE uploaded_files "
                    "ADD COLUMN IF NOT EXISTS file_id VARCHAR(64)"
                )
            )
        _schema_ready = True


async def close_async_engine() -> None:
    global _async_engine, _schema_ready
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
    _schema_ready = False
