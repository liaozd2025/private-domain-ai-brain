"""OpenAI 兼容适配层测试"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_orchestrator():
    """模拟编排器"""
    orch = MagicMock()
    orch.invoke = AsyncMock(return_value="这是 chat 模式回答。")

    async def mock_stream(*args, **kwargs):
        for token in ["这", "是", "流", "式", "回", "答"]:
            yield token

    orch.stream = mock_stream
    return orch


@pytest.fixture
def mock_plan_runner():
    """模拟 plan 模式执行器"""
    runner = MagicMock()
    runner.invoke = AsyncMock(
        return_value=SimpleNamespace(
            content="这是 plan 执行结果。",
            plan=[
                {"content": "分析现状", "status": "in_progress"},
                {"content": "输出方案", "status": "pending"},
            ],
            model="mock-plan-model",
        )
    )

    async def mock_stream(*args, **kwargs):
        yield {
            "type": "plan",
            "content": [
                {"content": "分析现状", "status": "in_progress"},
                {"content": "输出方案", "status": "pending"},
            ],
            "thread_id": kwargs["thread_id"],
        }
        yield {"type": "token", "content": "执", "thread_id": kwargs["thread_id"]}
        yield {"type": "token", "content": "行", "thread_id": kwargs["thread_id"]}
        yield {"type": "done", "content": "", "thread_id": kwargs["thread_id"]}

    runner.stream = mock_stream
    return runner


@pytest.fixture
def client(mock_orchestrator, mock_plan_runner):
    """创建测试客户端"""
    with (
        patch("src.memory.checkpointer.init_checkpointer", AsyncMock()),
        patch("src.memory.checkpointer.close_checkpointer", AsyncMock()),
        patch(
            "src.agent.orchestrator.get_orchestrator",
            AsyncMock(return_value=mock_orchestrator),
        ),
        patch(
            "src.agent.plan_runner.get_plan_runner",
            AsyncMock(return_value=mock_plan_runner),
        ),
    ):
        from src.main import app

        with TestClient(app) as c:
            yield c


def test_openai_models_lists_adapter_aliases(client):
    """兼容层应返回 Cherry 可见的模型别名"""
    response = client.get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    model_ids = {item["id"] for item in data["data"]}
    assert "private-domain-auto" in model_ids
    assert "private-domain-chat" in model_ids
    assert "private-domain-plan" in model_ids


def test_openai_chat_completion_auto_model_routes_simple_prompt_to_chat(
    client,
    mock_orchestrator,
    mock_plan_runner,
):
    """auto 模型别名应对普通请求走 chat。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-auto",
            "messages": [{"role": "user", "content": "帮我分析今天门店转化率"}],
            "user": "auto_user_chat",
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "这是 chat 模式回答。"
    mock_orchestrator.invoke.assert_awaited_once()
    mock_plan_runner.invoke.assert_not_awaited()


def test_openai_chat_completion_auto_model_routes_planning_prompt_to_plan(
    client,
    mock_plan_runner,
):
    """auto 模型别名应对明显的规划执行请求走 plan。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-auto",
            "messages": [{"role": "user", "content": "先规划再执行一份会员召回方案"}],
            "user": "auto_user_plan",
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "计划" in content
    mock_plan_runner.invoke.assert_awaited_once()


def test_openai_chat_completion_uses_chat_model_alias(client, mock_orchestrator):
    """chat 模型别名应路由到普通编排器"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [
                {"role": "system", "content": "你是门店经营顾问"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "帮我分析今天门店转化率"},
            ],
            "user": "cherry_user_1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "这是 chat 模式回答。"

    call_kwargs = mock_orchestrator.invoke.call_args.kwargs
    assert call_kwargs["user_id"] == "cherry_user_1"
    assert "帮我分析今天门店转化率" in call_kwargs["message"]
    assert "system" in call_kwargs["message"]
    assert call_kwargs["attachments"] == []


def test_openai_chat_completion_plan_model_renders_plan_text(client, mock_plan_runner):
    """plan 模型别名应把结构化计划渲染到文本里"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-plan",
            "messages": [
                {"role": "user", "content": "先规划再执行一份会员召回方案"},
            ],
            "user": "planner_1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    assert "计划" in content
    assert "分析现状" in content
    assert "这是 plan 执行结果。" in content
    mock_plan_runner.invoke.assert_awaited_once()


def test_openai_chat_completion_stream_returns_sse_chunks(client):
    """stream=true 时应返回 OpenAI 风格 SSE"""
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [{"role": "user", "content": "输出流式结果"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert 'data: {"id":"' in body
    assert '"object":"chat.completion.chunk"' in body
    assert "[DONE]" in body


def test_openai_chat_completion_plan_stream_renders_plan_first(client):
    """plan 模式流式响应应先输出计划文本，再输出正文 token"""
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "private-domain-plan",
            "messages": [{"role": "user", "content": "先规划再执行促活方案"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "计划" in body
    assert "分析现状" in body
    assert "执" in body


def test_openai_chat_completion_plan_stream_falls_back_to_invoke_on_stream_error(
    client,
    mock_plan_runner,
):
    """plan 流式执行失败时应降级为 invoke，再本地输出 SSE"""
    async def broken_stream(*args, **kwargs):
        raise RuntimeError("upstream stream failed")
        yield

    mock_plan_runner.stream = broken_stream

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "private-domain-plan",
            "messages": [{"role": "user", "content": "先规划再执行会员促活方案"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "计划" in body
    assert "分析现状" in body
    assert "这是 plan 执行结果。" in body
    mock_plan_runner.invoke.assert_awaited()


def test_openai_chat_completion_rejects_unsupported_tools(client):
    """tools/function calling 首版应返回 400"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [{"role": "user", "content": "测试"}],
            "tools": [{"type": "function", "function": {"name": "demo", "parameters": {}}}],
        },
    )

    assert response.status_code == 400
    assert "暂不支持" in response.json()["detail"]


def test_openai_chat_completion_accepts_data_url_image(client, mock_orchestrator):
    """OpenAI 图片消息应被转换为内部图片附件"""
    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("utf-8")
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "分析这张经营数据截图"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    attachments = mock_orchestrator.invoke.call_args.kwargs["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["file_type"] == "image"
    assert attachments[0]["file_path"].endswith(".png")
