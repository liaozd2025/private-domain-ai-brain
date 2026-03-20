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
    title VARCHAR(500),
    channel VARCHAR(50) DEFAULT 'web',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW(),
    message_count INTEGER DEFAULT 0,
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

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_conv_meta_user ON conversation_metadata(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active
    ON conversation_metadata(user_id, is_deleted, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_thread ON uploaded_files(thread_id);

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

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
