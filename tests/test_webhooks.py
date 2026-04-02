"""Webhook 处理器测试。"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import sys
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_webhooks_xml_parser_falls_back_when_defusedxml_missing(monkeypatch):
    """缺少 defusedxml 时，webhooks 模块仍应可导入并回退到标准库解析器。"""
    sys.modules.pop("src.api.webhooks", None)

    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "defusedxml.ElementTree":
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    module = importlib.import_module("src.api.webhooks")
    parser = module._get_xml_parser()

    assert module is not None
    assert parser.__name__ == "xml.etree.ElementTree"


def test_main_import_survives_when_oss2_missing(monkeypatch):
    """缺少 oss2 时，主应用仍应可导入，只有实际 OSS 操作才失败。"""
    for module_name in (
        "src.main",
        "src.api.routes",
        "src.api.openai_compat",
        "src.storage.oss",
    ):
        sys.modules.pop(module_name, None)

    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "oss2":
            raise ModuleNotFoundError(name)
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    module = importlib.import_module("src.main")

    assert module is not None
    assert module.app is not None


def test_openclaw_webhook_rejects_invalid_signature():
    """OpenClaw webhook 在配置密钥后必须校验签名。"""
    with (
        patch("src.memory.checkpointer.init_checkpointer", AsyncMock()),
        patch("src.memory.checkpointer.close_checkpointer", AsyncMock()),
        patch("src.api.webhooks.settings.openclaw_webhook_secret", "test-secret"),
        patch("src.api.webhooks.handle_openclaw_message", AsyncMock()),
    ):
        from src.main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/openclaw",
                json={
                    "event_type": "message",
                    "user_id": "cust_001",
                    "message": "你好",
                },
                headers={"X-OpenClaw-Signature": "sha256=bad-signature"},
            )

    assert response.status_code == 403


def test_openclaw_webhook_accepts_valid_signature():
    """OpenClaw webhook 签名正确时应接受请求并调度后台任务。"""
    body = b'{"event_type":"message","user_id":"cust_001","message":"\xe4\xbd\xa0\xe5\xa5\xbd"}'
    signature = "sha256=" + hmac.new(
        b"test-secret",
        body,
        hashlib.sha256,
    ).hexdigest()
    mocked_handler = AsyncMock()

    with (
        patch("src.memory.checkpointer.init_checkpointer", AsyncMock()),
        patch("src.memory.checkpointer.close_checkpointer", AsyncMock()),
        patch("src.api.webhooks.settings.openclaw_webhook_secret", "test-secret"),
        patch("src.api.webhooks.handle_openclaw_message", mocked_handler),
    ):
        from src.main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/openclaw",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-OpenClaw-Signature": signature,
                },
            )

    assert response.status_code == 200
    mocked_handler.assert_awaited_once()
