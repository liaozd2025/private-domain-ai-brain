"""用户画像存储测试"""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_profile_store_degrades_gracefully_when_asyncpg_missing():
    """缺少 asyncpg 时应优雅降级，不影响主流程"""
    from src.memory.store import UserProfileStore

    store = UserProfileStore()
    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ModuleNotFoundError("No module named 'asyncpg'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        first_profile = await store.get_profile("user-1")
        second_profile = await store.get_profile("user-1")
        updated = await store.update_profile("user-1", {"topics": ["私域运营"]})

    assert first_profile == {}
    assert second_profile == {}
    assert updated is False
    assert store._disabled_reason == "asyncpg_unavailable"
