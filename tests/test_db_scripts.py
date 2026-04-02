from pathlib import Path


def test_conversation_migration_sql_exists_for_existing_databases():
    """会话管理必须提供独立增量 SQL，不能只依赖 init_db。"""
    migration_path = Path("scripts/migrations/2026-03-20-add-conversation-metadata.sql")

    assert migration_path.exists()

    content = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS conversation_metadata" in content
    assert "ADD COLUMN IF NOT EXISTS is_deleted" in content
    assert "ADD COLUMN IF NOT EXISTS deleted_at" in content
    assert "CREATE INDEX IF NOT EXISTS idx_conv_meta_user_active" in content


def test_customer_service_migration_sql_exists_for_existing_databases():
    """客服与人工接管能力必须提供独立增量 SQL。"""
    migration_path = Path("scripts/migrations/2026-03-20-add-customer-service-support.sql")

    assert migration_path.exists()

    content = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS customer_service_messages" in content
    assert "CREATE TABLE IF NOT EXISTS human_handoffs" in content
    assert "ADD COLUMN IF NOT EXISTS user_role" in content
    assert "idx_human_handoffs_active_thread" in content


def test_conversation_messages_migration_sql_exists_for_new_session_model():
    """统一消息明细模型必须提供独立增量 SQL。"""
    migration_path = Path("scripts/migrations/2026-03-23-add-conversation-messages.sql")

    assert migration_path.exists()

    content = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS conversation_messages" in content
    assert "message_source" in content
    assert "idx_conversation_messages_thread_desc" in content


def test_init_db_contains_unified_conversation_schema():
    """初始化脚本必须直接包含统一会话消息表，避免新环境缺表。"""
    init_path = Path("scripts/init_db.sql")

    content = init_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS conversation_messages" in content
    assert "message_source" in content
