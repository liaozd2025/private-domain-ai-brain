"""OpenAI 兼容适配层测试"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.storage.oss import OSSStorageError


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
def mock_customer_service_supervisor():
    """模拟客服编排器。"""
    supervisor = MagicMock()
    supervisor.invoke = AsyncMock(
        return_value=SimpleNamespace(
            content="这个问题我暂时无法准确回答，已为您转接人工客服，请稍候。"
        )
    )

    async def mock_stream(*args, **kwargs):
        for token in "这个问题我暂时无法准确回答，已为您转接人工客服，请稍候。":
            yield token

    supervisor.stream = MagicMock(side_effect=mock_stream)
    return supervisor


@pytest.fixture
def client(mock_orchestrator, mock_plan_runner, mock_customer_service_supervisor):
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
        patch(
            "src.api.openai_compat.get_customer_service_supervisor",
            AsyncMock(return_value=mock_customer_service_supervisor),
            create=True,
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


def test_openai_chat_completion_transfer_request_routes_to_customer_service(
    client,
    mock_orchestrator,
    mock_customer_service_supervisor,
):
    """兼容层收到明确“转人工”请求时应进入客服转人工流程。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [
                {"role": "user", "content": "转人工"},
            ],
            "user": "customer_001",
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "已为您转接人工客服" in content
    mock_customer_service_supervisor.invoke.assert_awaited_once()
    mock_orchestrator.invoke.assert_not_awaited()


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


def test_openai_chat_completion_transfer_stream_routes_to_customer_service(
    client,
    mock_customer_service_supervisor,
):
    """兼容层流式请求在“转人工”时也应走客服链路。"""
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "messages": [{"role": "user", "content": "转人工"}],
            "user": "customer_001",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"content":"已"' in body
    assert '"content":"转"' in body
    assert '"content":"人"' in body
    mock_customer_service_supervisor.stream.assert_called_once()


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


def test_openai_chat_completion_accepts_data_url_image(client, mock_orchestrator, tmp_path):
    """OpenAI 图片消息应被转换为内部图片附件"""
    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("utf-8")
    )
    upload_root = tmp_path / "uploads"

    def _fake_materialize(*, object_key: str, file_id: str, user_id: str, suffix: str) -> str:
        local_path = upload_root / "oss_cache" / user_id / f"{file_id}{suffix}"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(image_bytes)
        return str(local_path)

    with (
        patch("src.api.openai_compat.oss_upload_bytes", return_value="uploads/openai_compat/a.png"),
        patch("src.config.settings.upload_dir", str(upload_root)),
        patch(
            "src.api.openai_compat.materialize_attachment_from_oss",
            side_effect=_fake_materialize,
        ),
    ):
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
    assert "oss_cache/openai_compat/" in attachments[0]["file_path"]


def test_openai_chat_completion_returns_503_when_image_oss_materialization_fails(client):
    """OpenAI 兼容层图片已上传到 OSS 后，如果回读缓存失败，应返回 503。"""
    image_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("utf-8")
    )

    with (
        patch("src.api.openai_compat.oss_upload_bytes", return_value="uploads/openai_compat/a.png"),
        patch(
            "src.api.openai_compat.materialize_attachment_from_oss",
            side_effect=OSSStorageError("OSS 下载失败: timeout"),
        ),
    ):
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

    assert response.status_code == 503
    assert response.json()["detail"] == "文件存储服务暂时不可用，请稍后重试"


def test_openai_chat_completion_returns_generated_thread_id_and_records_metadata(
    client,
    mock_orchestrator,
):
    """新会话应返回 thread_id，并写入会话元数据。"""
    store = MagicMock()
    store.upsert_on_turn = AsyncMock()

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "private-domain-chat",
                "messages": [{"role": "user", "content": "帮我分析今天门店业绩"}],
                "user": "boss_001",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"].startswith("thread_")
    store.upsert_on_turn.assert_awaited_once()

    call_kwargs = mock_orchestrator.invoke.call_args.kwargs
    assert call_kwargs["thread_id"] == data["thread_id"]


def test_openai_chat_completion_prefers_top_level_session_fields_and_store_id(
    client,
    mock_orchestrator,
):
    """顶层 thread_id/user_role/store_id 应覆盖 metadata 并透传。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "thread_id": "thread_existing_1",
            "user_role": "门店老板",
            "store_id": "store_top",
            "metadata": {
                "thread_id": "thread_from_metadata",
                "user_role": "unknown",
                "store_id": "store_meta",
            },
            "messages": [{"role": "user", "content": "看一下这家店本周表现"}],
            "user": "boss_001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "thread_existing_1"

    call_kwargs = mock_orchestrator.invoke.call_args.kwargs
    assert call_kwargs["thread_id"] == "thread_existing_1"
    assert call_kwargs["user_role"] == "门店老板"
    assert call_kwargs["store_id"] == "store_top"


def test_openai_chat_completion_with_thread_id_only_uses_current_turn_messages(
    client,
    mock_orchestrator,
):
    """已有 thread_id 时，不应把旧 assistant/user 历史再次拼进当前 turn。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "private-domain-chat",
            "thread_id": "thread_existing_2",
            "messages": [
                {"role": "system", "content": "你是门店经营顾问"},
                {"role": "user", "content": "昨天的老问题"},
                {"role": "assistant", "content": "昨天的老回答"},
                {"role": "user", "content": "今天继续看这个门店"},
            ],
            "user": "boss_001",
        },
    )

    assert response.status_code == 200
    prompt = mock_orchestrator.invoke.call_args.kwargs["message"]
    assert "你是门店经营顾问" in prompt
    assert "今天继续看这个门店" in prompt
    assert "昨天的老问题" not in prompt
    assert "昨天的老回答" not in prompt


def test_openai_chat_completion_stream_emits_thread_id_and_records_metadata(
    client,
    mock_orchestrator,
):
    """流式 chat 新会话应在 SSE 中暴露 thread_id，并写入会话元数据。"""
    store = MagicMock()
    store.upsert_on_turn = AsyncMock()

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "private-domain-chat",
                "messages": [{"role": "user", "content": "给我一个会员召回建议"}],
                "stream": True,
                "user": "boss_001",
            },
        ) as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"thread_id":"thread_' in body
    store.upsert_on_turn.assert_awaited_once()
    assert mock_orchestrator.stream is not None


def test_openai_chat_completion_plan_stream_reuses_requested_thread_id(
    client,
):
    """plan 流式响应应复用请求里的 thread_id，不再生成新的 oa_* 线程。"""
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "private-domain-plan",
            "thread_id": "thread_resume_plan_1",
            "messages": [{"role": "user", "content": "继续执行上次的会员促活方案"}],
            "stream": True,
            "user": "boss_001",
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"thread_id":"thread_resume_plan_1"' in body
    assert '"thread_id":"oa_' not in body
