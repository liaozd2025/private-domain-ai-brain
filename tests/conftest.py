"""全局测试配置 — 禁用 API 认证，简化测试环境。"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def disable_auth():
    """所有测试默认关闭 API 认证，避免每个测试都需要构造凭证。"""
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.auth_enabled = False
        yield mock_settings


@pytest.fixture
def mock_checkpointer():
    """Mock checkpointer 避免真实 DB 连接。"""
    with (
        patch("src.memory.checkpointer.init_checkpointer", AsyncMock()),
        patch("src.memory.checkpointer.close_checkpointer", AsyncMock()),
    ):
        yield
