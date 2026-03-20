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
