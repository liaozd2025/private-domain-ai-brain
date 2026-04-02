"""用户画像存储测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_profile_store_degrades_gracefully_when_engine_init_fails():
    """SQLAlchemy engine 初始化失败时应优雅降级，不影响主流程。"""
    from src.memory.store import UserProfileStore

    store = UserProfileStore()
    with patch("src.memory.store.get_async_engine", side_effect=RuntimeError("boom")):
        first_profile = await store.get_profile("user-1")
        second_profile = await store.get_profile("user-1")
        updated = await store.update_profile("user-1", {"topics": ["私域运营"]})

    assert first_profile == {}
    assert second_profile == {}
    assert updated is False
    assert store._disabled_reason == "engine_init_failed"


@pytest.mark.asyncio
async def test_profile_store_uses_sqlalchemy_select_result_mappings():
    """用户画像读取应消费 SQLAlchemy result.mappings()。"""
    from src.memory.store import UserProfileStore

    row = {
        "role": "门店老板",
        "preferences": '{"tone":"direct"}',
        "topics": '["复购","拉新"]',
    }
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=result)
    connection_cm = MagicMock()
    connection_cm.__aenter__ = AsyncMock(return_value=conn)
    connection_cm.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = connection_cm

    store = UserProfileStore()
    store._get_engine = MagicMock(return_value=engine)
    with patch("src.memory.store.ensure_managed_schema", AsyncMock()):
        profile = await store.get_profile("user-1")

    stmt = conn.execute.call_args.args[0]
    assert not isinstance(stmt, str)
    assert profile["role"] == "门店老板"
    assert profile["topics"] == ["复购", "拉新"]
