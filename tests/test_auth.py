"""API 认证测试 — app_id + secret_key 双模式认证。"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


TEST_APP_ID = "app_test123"
TEST_SECRET = "sk_testsecret"
TEST_APP_NAME = "Test App"


def _make_cached_cred(is_active: bool = True):
    from src.api.auth import _CachedCredential
    return _CachedCredential(
        secret_hash=_sha256(TEST_SECRET),
        is_active=is_active,
        app_name=TEST_APP_NAME,
        cached_at=time.monotonic(),
    )


async def _lookup_active(app_id: str):
    if app_id == TEST_APP_ID:
        return _make_cached_cred(is_active=True)
    return None


async def _lookup_disabled(app_id: str):
    if app_id == TEST_APP_ID:
        return _make_cached_cred(is_active=False)
    return None


async def _lookup_none(_app_id: str):
    return None


@contextmanager
def _auth_client(lookup_fn=_lookup_none, auth_enabled: bool = True):
    """创建带认证 mock 的 TestClient。"""
    from src.main import app

    with (
        patch("src.memory.checkpointer.init_checkpointer", AsyncMock()),
        patch("src.memory.checkpointer.close_checkpointer", AsyncMock()),
        patch("src.api.auth.settings") as mock_settings,
        patch("src.api.auth._lookup_credential", side_effect=lookup_fn),
    ):
        mock_settings.auth_enabled = auth_enabled
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


# ---------------------------------------------------------------------------
# 测试：auth_enabled=False 跳过认证
# ---------------------------------------------------------------------------


def test_auth_disabled_allows_all():
    """auth_enabled=False 时，无凭证也能访问受保护端点。"""
    with _auth_client(auth_enabled=False) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 测试：公开路径跳过认证
# ---------------------------------------------------------------------------


def test_health_public_no_auth():
    """health 端点不需要凭证。"""
    with _auth_client(auth_enabled=True) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 测试：无凭证 → 401
# ---------------------------------------------------------------------------


def test_no_credentials_returns_401():
    """无 Header 无 Bearer → 401。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.post("/api/v1/chat", json={"message": "hi"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 测试：自定义 Header 认证
# ---------------------------------------------------------------------------


def test_custom_header_valid():
    """X-App-Id + X-App-Secret 有效 → 通过（不是 401/403）。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-App-Id": TEST_APP_ID, "X-App-Secret": TEST_SECRET},
        )
    assert resp.status_code not in (401, 403)


def test_custom_header_wrong_secret():
    """X-App-Id + 错误 secret → 401。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-App-Id": TEST_APP_ID, "X-App-Secret": "wrong"},
        )
    assert resp.status_code == 401


def test_custom_header_unknown_app_id():
    """未知 app_id → 401。"""
    with _auth_client(lookup_fn=_lookup_none, auth_enabled=True) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-App-Id": "app_unknown", "X-App-Secret": TEST_SECRET},
        )
    assert resp.status_code == 401


def test_disabled_credential_returns_403():
    """is_active=False 的凭证 → 403。"""
    with _auth_client(lookup_fn=_lookup_disabled, auth_enabled=True) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-App-Id": TEST_APP_ID, "X-App-Secret": TEST_SECRET},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 测试：Bearer token（OpenAI 兼容层）
# ---------------------------------------------------------------------------


def test_bearer_token_valid():
    """Bearer <app_id>:<secret_key> 有效 → 通过。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {TEST_APP_ID}:{TEST_SECRET}"},
        )
    assert resp.status_code not in (401, 403)


def test_bearer_token_wrong_secret():
    """Bearer 错误 secret → 401。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {TEST_APP_ID}:wrong"},
        )
    assert resp.status_code == 401


def test_bearer_token_no_colon():
    """Bearer 格式无冒号 → 401（无法解析 app_id:secret）。"""
    with _auth_client(lookup_fn=_lookup_active, auth_enabled=True) as client:
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": "Bearer just_a_token"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 测试：工具函数
# ---------------------------------------------------------------------------


def test_hash_secret_deterministic():
    """相同 secret 哈希相同，不同 secret 哈希不同。"""
    from src.api.auth import _hash_secret
    assert _hash_secret("foo") == _hash_secret("foo")
    assert _hash_secret("foo") != _hash_secret("bar")


def test_invalidate_cache():
    """invalidate_cache 移除缓存条目。"""
    from src.api.auth import _CachedCredential, _cache, invalidate_cache

    _cache["app_temp"] = _CachedCredential(
        secret_hash="h", is_active=True, app_name="temp", cached_at=time.monotonic()
    )
    assert "app_temp" in _cache
    invalidate_cache("app_temp")
    assert "app_temp" not in _cache
