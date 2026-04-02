-- 客服智能体与人工接管支持

ALTER TABLE conversation_metadata
    ADD COLUMN IF NOT EXISTS user_role VARCHAR(50) DEFAULT 'unknown';

CREATE TABLE IF NOT EXISTS customer_service_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'web',
    sender_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_service_messages_thread
    ON customer_service_messages(thread_id, created_at ASC);

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

CREATE INDEX IF NOT EXISTS idx_human_handoffs_status
    ON human_handoffs(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_human_handoffs_thread
    ON human_handoffs(thread_id, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_human_handoffs_active_thread
    ON human_handoffs(thread_id)
    WHERE status IN ('pending', 'claimed');
