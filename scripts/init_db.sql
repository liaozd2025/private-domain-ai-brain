-- AI 智脑助手数据库初始化脚本
-- LangGraph checkpointer 和 store 表由 langgraph-checkpoint-postgres 自动创建

-- 用户画像表 (扩展 LangGraph store)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id VARCHAR(255) PRIMARY KEY,
    role VARCHAR(50) DEFAULT 'unknown',
    preferences JSONB DEFAULT '{}',
    topics JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 对话元数据表
CREATE TABLE IF NOT EXISTS conversation_metadata (
    thread_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255),
    user_role VARCHAR(50) DEFAULT 'unknown',
    title VARCHAR(500),
    channel VARCHAR(50) DEFAULT 'web',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW(),
    message_count INTEGER DEFAULT 0,
    message_source VARCHAR(20) NOT NULL DEFAULT 'legacy',
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ
);

-- 文件上传记录
CREATE TABLE IF NOT EXISTS uploaded_files (
    id SERIAL PRIMARY KEY,
    thread_id VARCHAR(255),
    user_id VARCHAR(255),
    filename VARCHAR(500),
    file_path TEXT,
    file_type VARCHAR(50),
    file_size_bytes INTEGER,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- 客服消息记录
CREATE TABLE IF NOT EXISTS customer_service_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'web',
    sender_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 统一会话消息明细
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

-- 人工接管队列
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
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_conv_meta_user ON conversation_metadata(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active
    ON conversation_metadata(user_id, is_deleted, message_source, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_thread ON uploaded_files(thread_id);
CREATE INDEX IF NOT EXISTS idx_customer_service_messages_thread
    ON customer_service_messages(thread_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_desc
    ON conversation_messages(thread_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_asc
    ON conversation_messages(thread_id, created_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_human_handoffs_status
    ON human_handoffs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_human_handoffs_thread
    ON human_handoffs(thread_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_human_handoffs_active_thread
    ON human_handoffs(thread_id)
    WHERE status IN ('pending', 'claimed');

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS user_role VARCHAR(50) DEFAULT 'unknown';

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS message_source VARCHAR(20) NOT NULL DEFAULT 'legacy';

-- 更新时间自动触发器
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- API 凭证表
CREATE TABLE IF NOT EXISTS api_credentials (
    app_id      VARCHAR(64)  PRIMARY KEY,
    secret_hash VARCHAR(128) NOT NULL,
    app_name    VARCHAR(255) NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_credentials_active
    ON api_credentials(app_id) WHERE is_active = TRUE;

CREATE TRIGGER api_credentials_updated_at
    BEFORE UPDATE ON api_credentials
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
