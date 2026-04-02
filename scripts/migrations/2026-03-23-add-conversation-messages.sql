-- 统一会话消息明细迁移

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS message_source VARCHAR(20) NOT NULL DEFAULT 'legacy';

CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'web',
    store_id VARCHAR(255),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_desc
    ON conversation_messages(thread_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_asc
    ON conversation_messages(thread_id, created_at ASC, id ASC);

CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active
    ON conversation_metadata(user_id, is_deleted, message_source, last_message_at DESC);
