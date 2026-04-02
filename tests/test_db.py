"""SQLAlchemy 数据库层测试。"""


def test_settings_exposes_async_database_url_for_sqlalchemy():
    """SQLAlchemy 异步引擎应与项目其余数据库栈一致，使用 psycopg 驱动连接串。"""
    from src.config import Settings

    settings = Settings(
        postgres_host="localhost",
        postgres_port=5433,
        postgres_db="ai_brain",
        postgres_user="ai_brain",
        postgres_password="changeme",
    )

    assert settings.database_url_async == (
        "postgresql+psycopg://ai_brain:changeme@localhost:5433/ai_brain"
    )
