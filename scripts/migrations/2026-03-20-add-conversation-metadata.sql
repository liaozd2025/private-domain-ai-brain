-- 增量迁移：为现有数据库补齐会话元数据表及软删除字段
-- 执行方式：
--   psql "$DATABASE_URL" -f scripts/migrations/2026-03-20-add-conversation-metadata.sql

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
);

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS user_id VARCHAR(255);

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS title VARCHAR(500);

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS channel VARCHAR(50) DEFAULT 'web';

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0;

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_conv_meta_user
    ON conversation_metadata(user_id);

CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active
    ON conversation_metadata(user_id, is_deleted, last_message_at DESC);
