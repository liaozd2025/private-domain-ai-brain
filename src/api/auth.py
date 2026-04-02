"""API 身份认证 — app_id + secret_key 双模式认证。"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

import structlog
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from src.config import settings
from src.memory.db import api_credentials_table, get_async_engine

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

_CACHE_TTL = 60  # 秒


@dataclass
class _CachedCredential:
    secret_hash: str
    is_active: bool
    app_name: str
    cached_at: float


_cache: dict[str, _CachedCredential] = {}

# 无需认证的路径
_PUBLIC_PATHS = {"/api/v1/health"}

# Bearer 方案（auto_error=False 让我们自己控制错误）
_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def _lookup_credential(app_id: str) -> _CachedCredential | None:
    now = time.monotonic()
    cached = _cache.get(app_id)
    if cached and (now - cached.cached_at) < _CACHE_TTL:
        return cached

    engine = get_async_engine()
    async with engine.connect() as conn:
        row = await conn.execute(
            select(
                api_credentials_table.c.secret_hash,
                api_credentials_table.c.is_active,
                api_credentials_table.c.app_name,
            ).where(api_credentials_table.c.app_id == app_id)
        )
        result = row.first()

    if result is None:
        _cache.pop(app_id, None)
        return None

    entry = _CachedCredential(
        secret_hash=result.secret_hash,
        is_active=result.is_active,
        app_name=result.app_name,
        cached_at=now,
    )
    _cache[app_id] = entry
    return entry


async def _verify(app_id: str, secret_key: str) -> _CachedCredential:
    """验证凭证，失败抛 HTTPException。"""
    cred = await _lookup_credential(app_id)
    if cred is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not cred.is_active:
        raise HTTPException(status_code=403, detail="Credential disabled")
    if cred.secret_hash != _hash_secret(secret_key):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return cred


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------


async def _verify_app_headers(
    x_app_id: str | None = Header(None, alias="X-App-Id"),
    x_app_secret: str | None = Header(None, alias="X-App-Secret"),
) -> _CachedCredential | None:
    """自定义 Header 认证（主 API 使用）。"""
    if not x_app_id or not x_app_secret:
        return None
    return await _verify(x_app_id, x_app_secret)


async def _verify_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> _CachedCredential | None:
    """Bearer token 认证，格式 Bearer <app_id>:<secret_key>（OpenAI 兼容层使用）。"""
    if not credentials:
        return None
    token = credentials.credentials
    if ":" not in token:
        return None
    app_id, secret_key = token.split(":", 1)
    return await _verify(app_id, secret_key)


async def require_auth(
    request: Request,
    header_cred: _CachedCredential | None = Depends(_verify_app_headers),
    bearer_cred: _CachedCredential | None = Depends(_verify_bearer),
) -> _CachedCredential | None:
    """主认证依赖。任一方式通过即可，公开路径直接跳过。"""
    if not settings.auth_enabled:
        return None

    if request.url.path in _PUBLIC_PATHS:
        return None

    cred = header_cred or bearer_cred
    if cred is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return cred


# ---------------------------------------------------------------------------
# 管理工具
# ---------------------------------------------------------------------------


async def create_api_credential(app_name: str) -> tuple[str, str]:
    """创建 API 凭证，返回 (app_id, secret_key)，secret 仅此一次可见。"""
    app_id = f"app_{secrets.token_hex(16)}"
    secret_key = f"sk_{secrets.token_hex(32)}"

    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.execute(
            api_credentials_table.insert().values(
                app_id=app_id,
                secret_hash=_hash_secret(secret_key),
                app_name=app_name,
            )
        )

    logger.info("创建 API 凭证", app_id=app_id, app_name=app_name)
    return app_id, secret_key


def invalidate_cache(app_id: str) -> None:
    """手动失效缓存（禁用凭证后调用）。"""
    _cache.pop(app_id, None)
