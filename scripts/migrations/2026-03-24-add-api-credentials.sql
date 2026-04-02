-- Migration: 2026-03-24-add-api-credentials
-- 新增 API 凭证表，用于 app_id + secret_key 身份认证

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
