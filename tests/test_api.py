"""API 端点集成测试"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.memory.attachments import AttachmentNotFoundError, AttachmentStorageError
from src.storage.oss import OSSStorageError


class _FakeBeginContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self):
        self.conn = AsyncMock()

    def begin(self):
        return _FakeBeginContext(self.conn)


@pytest.fixture
def mock_orchestrator():
    """模拟编排器"""
    orch = MagicMock()
    orch.invoke = AsyncMock(return_value="这是 AI 的回答。")

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
            content="这是 plan 模式的回答。",
            plan=[
                {"content": "分析当前数据", "status": "in_progress"},
                {"content": "制定执行动作", "status": "pending"},
            ],
            model="mock-plan-model",
        )
    )

    async def mock_stream(*args, **kwargs):
        yield {
            "type": "plan",
            "content": [
                {"task_id": "task_1", "content": "分析当前数据", "status": "in_progress"},
                {"task_id": "task_2", "content": "制定执行动作", "status": "pending"},
            ],
            "thread_id": kwargs["thread_id"],
        }
        yield {
            "type": "task",
            "content": {
                "task_id": "task_1",
                "content": "分析当前数据",
                "status": "in_progress",
            },
            "thread_id": kwargs["thread_id"],
        }
        yield {
            "type": "tool",
            "content": {
                "task_id": "task_1",
                "tool_name": "analyze_uploaded_data",
                "display_name": "分析表格数据",
                "status": "started",
                "summary": "开始分析当前上传的表格数据",
                "duration_ms": None,
            },
            "thread_id": kwargs["thread_id"],
        }
        yield {"type": "token", "content": "计"}
        yield {"type": "token", "content": "划"}
        yield {"type": "done", "content": "", "thread_id": kwargs["thread_id"]}

    runner.stream = mock_stream
    return runner


@pytest.fixture
def mock_customer_service_supervisor():
    """模拟客服编排器。"""
    supervisor = MagicMock()
    supervisor.invoke = AsyncMock(
        return_value=SimpleNamespace(content="这是客服知识库回答。")
    )

    async def mock_stream(*args, **kwargs):
        yield "客"
        yield "服"
        yield "回"
        yield "答"

    supervisor.stream = mock_stream
    return supervisor


@pytest.fixture
def mock_customer_service_store():
    """模拟客服存储。"""
    store = MagicMock()
    store.list_handoffs = AsyncMock(
        return_value={
            "items": [
                {
                    "id": "handoff_1",
                    "thread_id": "thread_customer_1",
                    "user_id": "cust_001",
                    "channel": "web",
                    "status": "pending",
                    "reason": "知识库未命中",
                    "last_customer_message": "退款怎么处理",
                    "claimed_by": None,
                    "claimed_at": None,
                    "resolved_at": None,
                    "created_at": "2026-03-20T12:00:00+08:00",
                    "updated_at": "2026-03-20T12:00:00+08:00",
                }
            ],
            "total": 1,
        }
    )
    store.get_handoff_detail = AsyncMock(
        return_value={
            "id": "handoff_1",
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "channel": "web",
            "status": "pending",
            "reason": "知识库未命中",
            "last_customer_message": "退款怎么处理",
            "claimed_by": None,
            "claimed_at": None,
            "resolved_at": None,
            "created_at": "2026-03-20T12:00:00+08:00",
            "updated_at": "2026-03-20T12:00:00+08:00",
            "messages": [
                {
                    "sender_type": "customer",
                    "content": "退款怎么处理",
                    "created_at": "2026-03-20T12:00:00+08:00",
                }
            ],
        }
    )
    store.claim_handoff = AsyncMock(
        return_value={
            "id": "handoff_1",
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "channel": "web",
            "status": "claimed",
            "reason": "知识库未命中",
            "last_customer_message": "退款怎么处理",
            "claimed_by": "agent_a",
            "claimed_at": "2026-03-20T12:05:00+08:00",
            "resolved_at": None,
            "created_at": "2026-03-20T12:00:00+08:00",
            "updated_at": "2026-03-20T12:05:00+08:00",
        }
    )
    store.reply_to_handoff = AsyncMock(
        return_value={
            "id": "handoff_1",
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "channel": "web",
            "status": "claimed",
            "reason": "知识库未命中",
            "last_customer_message": "退款怎么处理",
            "claimed_by": "agent_a",
            "claimed_at": "2026-03-20T12:05:00+08:00",
            "resolved_at": None,
            "created_at": "2026-03-20T12:00:00+08:00",
            "updated_at": "2026-03-20T12:06:00+08:00",
        }
    )
    store.resolve_handoff = AsyncMock(
        return_value={
            "id": "handoff_1",
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "channel": "web",
            "status": "resolved",
            "reason": "知识库未命中",
            "last_customer_message": "退款怎么处理",
            "claimed_by": "agent_a",
            "claimed_at": "2026-03-20T12:05:00+08:00",
            "resolved_at": "2026-03-20T12:08:00+08:00",
            "created_at": "2026-03-20T12:00:00+08:00",
            "updated_at": "2026-03-20T12:08:00+08:00",
        }
    )
    store.is_customer_thread = AsyncMock(return_value=True)
    store.get_thread_messages = AsyncMock(
        return_value=[
            {
                "sender_type": "customer",
                "content": "退款怎么处理",
                "created_at": "2026-03-20T12:00:00+08:00",
            },
            {
                "sender_type": "system",
                "content": "这个问题我暂时无法准确回答，已为您转接人工客服，请稍候。",
                "created_at": "2026-03-20T12:00:01+08:00",
            },
            {
                "sender_type": "human",
                "content": "您好，我来继续帮您处理。",
                "created_at": "2026-03-20T12:05:00+08:00",
            },
        ]
    )
    return store


def _install_optional_override(app, module_name: str, attr_name: str, provider) -> None:
    module = importlib.import_module(module_name)
    dependency = getattr(module, attr_name, None)
    if dependency is not None:
        app.dependency_overrides[dependency] = provider


@pytest.fixture
def client(
    mock_orchestrator,
    mock_plan_runner,
    mock_customer_service_supervisor,
    mock_customer_service_store,
):
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
            "src.api.streaming.get_customer_service_supervisor",
            AsyncMock(return_value=mock_customer_service_supervisor),
            create=True,
        ),
    ):
        from src.main import app

        with TestClient(app) as c:
            _install_optional_override(
                app,
                "src.api.routes",
                "get_customer_service_supervisor_dep",
                lambda: mock_customer_service_supervisor,
            )
            _install_optional_override(
                app,
                "src.api.routes",
                "get_customer_service_store_dep",
                lambda: mock_customer_service_store,
            )
            yield c
            app.dependency_overrides.clear()


def test_health_check(client):
    """健康检查端点应返回 ok"""
    with patch("src.memory.checkpointer.get_checkpointer", AsyncMock()):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


def test_health_check_redacts_internal_errors(client):
    """健康检查降级时不应向外暴露底层异常文本。"""
    with (
        patch(
            "src.memory.checkpointer.get_checkpointer",
            AsyncMock(side_effect=RuntimeError("db connection leaked")),
        ),
        patch("src.api.routes._check_milvus_health", AsyncMock(return_value="error")),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["database"] == "error"
    assert "db connection leaked" not in response.text


def test_chat_basic(client, mock_orchestrator):
    """基本聊天端点测试"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "你好",
            "user_id": "test_user",
            "user_role": "门店老板",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert "thread_id" in data
    assert data["content"] == "这是 AI 的回答。"
    assert data["requested_mode"] == "auto"
    assert data["resolved_mode"] == "chat"
    assert data["mode"] == "chat"


def test_chat_generates_thread_id(client):
    """不传 thread_id 时应自动生成"""
    response = client.post(
        "/api/v1/chat",
        json={"message": "测试", "user_id": "user1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"].startswith("thread_")


@pytest.mark.parametrize("thread_id", ["", "   "])
def test_chat_blank_thread_id_generates_new_thread_and_persists_metadata(
    client,
    thread_id: str,
):
    """空字符串或纯空白 thread_id 应按新会话处理，并写入统一会话索引。"""
    store = MagicMock()
    store.save_user_message = AsyncMock()
    store.save_assistant_message = AsyncMock()

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "测试空白线程",
                "user_id": "user1",
                "thread_id": thread_id,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"].startswith("thread_")
    store.save_user_message.assert_awaited_once()
    assert store.save_user_message.await_args.kwargs["thread_id"] == data["thread_id"]


def test_chat_with_thread_id(client):
    """传入 thread_id 时应使用传入的值"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "测试",
            "user_id": "user1",
            "thread_id": "thread_custom_123",
        },
    )
    assert response.status_code == 200
    assert response.json()["thread_id"] == "thread_custom_123"


def test_chat_persists_unified_conversation_messages(client, mock_orchestrator):
    """聊天成功后应分两步写入：请求到达时写用户消息，回复后写 assistant 消息。"""
    store = MagicMock()
    store.save_user_message = AsyncMock()
    store.save_assistant_message = AsyncMock()

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "帮我分析一下本月门店经营",
                "user_id": "boss_001",
                "thread_id": "thread_meta_1",
            },
        )

    assert response.status_code == 200
    store.save_user_message.assert_awaited_once()
    user_kwargs = store.save_user_message.await_args.kwargs
    assert user_kwargs["thread_id"] == "thread_meta_1"
    assert user_kwargs["user_id"] == "boss_001"
    assert user_kwargs["channel"] == "web"
    assert user_kwargs["message"] == "帮我分析一下本月门店经营"

    store.save_assistant_message.assert_awaited_once()
    asst_kwargs = store.save_assistant_message.await_args.kwargs
    assert asst_kwargs["thread_id"] == "thread_meta_1"
    assert asst_kwargs["content"] == "这是 AI 的回答。"


def test_chat_empty_message(client):
    """空消息应返回 422"""
    response = client.post(
        "/api/v1/chat",
        json={"message": "", "user_id": "user1"},
    )
    assert response.status_code == 422


def test_file_upload(client, tmp_path):
    """文件上传测试"""
    test_file = tmp_path / "test.csv"
    test_file.write_text("名称,销售额\n门店A,10000\n门店B,20000")
    fake_engine = _FakeEngine()

    with (
        patch("src.api.routes.oss_upload_bytes", return_value="uploads/user1/abc.csv"),
        patch("src.api.routes.ensure_managed_schema", AsyncMock()),
        patch("src.api.routes.get_async_engine", return_value=fake_engine),
    ):
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("test.csv", open(test_file, "rb"), "text/csv")},
            data={"user_id": "user1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert data["filename"] == "test.csv"


def test_file_upload_image(client, tmp_path):
    """图片文件上传应被接受"""
    test_file = tmp_path / "poster.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-image-data")
    fake_engine = _FakeEngine()

    with (
        patch("src.api.routes.oss_upload_bytes", return_value="uploads/user1/abc.png"),
        patch("src.api.routes.ensure_managed_schema", AsyncMock()),
        patch("src.api.routes.get_async_engine", return_value=fake_engine),
    ):
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("poster.png", open(test_file, "rb"), "image/png")},
            data={"user_id": "user1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "poster.png"
    assert data["file_type"] == "image"


def test_file_upload_returns_503_when_oss_times_out(client, tmp_path):
    """OSS 超时应返回明确的 503，而不是未处理异常。"""
    test_file = tmp_path / "test.csv"
    test_file.write_text("名称,销售额\n门店A,10000\n门店B,20000")

    with patch(
        "src.api.routes.oss_upload_bytes",
        side_effect=OSSStorageError("OSS 上传失败: timeout"),
    ):
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("test.csv", open(test_file, "rb"), "text/csv")},
            data={"user_id": "user1"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "文件存储服务暂时不可用，请稍后重试"


def test_file_upload_unsupported_type(client, tmp_path):
    """不支持的文件类型应返回 400"""
    test_file = tmp_path / "test.exe"
    test_file.write_bytes(b"fake binary")

    response = client.post(
        "/api/v1/files/upload",
        files={"file": ("test.exe", open(test_file, "rb"), "application/octet-stream")},
    )
    assert response.status_code == 400


def test_chat_resolves_uploaded_attachment_by_file_id(client, mock_orchestrator, tmp_path):
    """聊天请求只传 file_id 时，应把已解析的 OSS 附件透传给编排器。"""
    upload_root = tmp_path / "uploads"
    file_id = "file_sales_001"
    resolved_path = upload_root / "oss_cache" / "user1" / f"{file_id}.csv"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text("门店,销售额\nA,100\nB,200", encoding="utf-8")

    with patch(
        "src.api.routes.resolve_attachment_refs_from_db",
        AsyncMock(
            return_value=[
                {
                    "file_id": file_id,
                    "filename": "sales.csv",
                    "file_type": "csv",
                    "file_path": str(resolved_path),
                }
            ]
        ),
    ):
        chat_response = client.post(
            "/api/v1/chat",
            json={
                "message": "帮我分析这个文件",
                "user_id": "user1",
                "attachments": [{"file_id": file_id}],
            },
        )

    assert chat_response.status_code == 200
    call_kwargs = mock_orchestrator.invoke.call_args.kwargs
    attachments = call_kwargs["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["file_id"] == file_id
    assert attachments[0]["filename"] == "sales.csv"
    assert attachments[0]["file_type"] == "csv"
    assert attachments[0]["file_path"] == str(resolved_path)


def test_chat_rejects_unknown_attachment_id(client):
    """未知附件 ID 应返回 400"""
    with patch(
        "src.api.routes.resolve_attachment_refs_from_db",
        AsyncMock(side_effect=AttachmentNotFoundError("附件不存在: missing-file-id")),
    ):
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "帮我看看这个文件",
                "user_id": "user1",
                "attachments": [{"file_id": "missing-file-id"}],
            },
        )
    assert response.status_code == 400


def test_chat_returns_503_when_attachment_oss_materialization_fails(client):
    """聊天接口在附件从 OSS 回读失败时应返回受控 503。"""
    with patch(
        "src.api.routes.resolve_attachment_refs_from_db",
        AsyncMock(side_effect=AttachmentStorageError("附件存储服务暂时不可用: file_sales_001")),
    ):
        chat_response = client.post(
            "/api/v1/chat",
            json={
                "message": "帮我分析这个文件",
                "user_id": "user1",
                "attachments": [{"file_id": "file_sales_001"}],
            },
        )

    assert chat_response.status_code == 503
    assert chat_response.json()["detail"] == "文件存储服务暂时不可用，请稍后重试"


def test_chat_plan_mode_returns_plan(client):
    """plan 模式应返回计划结构和模式标记"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "帮我先规划一份提升会员复购率的执行方案",
            "user_id": "planner_1",
            "mode": "plan",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "plan"
    assert data["requested_mode"] == "plan"
    assert data["resolved_mode"] == "plan"
    assert "plan" in data
    assert isinstance(data["plan"], list)
    assert data["content"] == "这是 plan 模式的回答。"


def test_chat_auto_mode_routes_planning_request_to_plan_runner(client, mock_plan_runner):
    """auto 模式下明显的规划执行请求应走 plan runner。"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "先规划再执行一份门店活动方案",
            "user_id": "planner_auto",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["requested_mode"] == "auto"
    assert data["resolved_mode"] == "plan"
    assert data["mode"] == "plan"
    mock_plan_runner.invoke.assert_awaited_once()


def test_chat_customer_role_routes_to_customer_service_supervisor(
    client,
    mock_orchestrator,
    mock_customer_service_supervisor,
):
    """customer 角色应走客服编排器，而不是内部运营编排器。"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "退款怎么处理？",
            "user_id": "cust_001",
            "user_role": "customer",
            "mode": "plan",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "这是客服知识库回答。"
    assert data["mode"] == "chat"
    assert data["resolved_mode"] == "chat"
    mock_customer_service_supervisor.invoke.assert_awaited_once()
    mock_orchestrator.invoke.assert_not_awaited()


def _parse_sse_events(text: str) -> list[dict]:
    """解析 SSE 响应文本为事件列表。"""
    import json as _json

    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data = _json.loads(line[6:])
        if event_type and data is not None:
            events.append({"type": event_type, **data})
    return events


def test_chat_stream_plan_mode_emits_mode_and_progress_events(client):
    """plan 流式接口应先发模式，再发计划和任务进度。"""
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "先规划再执行一份门店活动方案", "user_id": "planner_sse"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    events = _parse_sse_events(response.text)
    assert len(events) >= 7

    first_event = events[0]
    second_event = events[1]
    third_event = events[2]
    fourth_event = events[3]
    fifth_event = events[4]
    sixth_event = events[5]
    done_event = events[6]

    assert first_event["type"] == "mode"
    assert first_event["content"]["requested_mode"] == "auto"
    assert first_event["content"]["resolved_mode"] == "plan"
    assert second_event["type"] == "plan"
    assert isinstance(second_event["content"], list)
    assert third_event["type"] == "task"
    assert third_event["content"]["status"] == "in_progress"
    assert fourth_event["type"] == "tool"
    assert fourth_event["content"]["tool_name"] == "analyze_uploaded_data"
    assert fifth_event["type"] == "token"
    assert sixth_event["type"] == "token"
    assert done_event["type"] == "done"
    assert done_event["requested_mode"] == "auto"
    assert done_event["resolved_mode"] == "plan"


@pytest.mark.parametrize("thread_id", ["", "   "])
def test_chat_stream_blank_thread_id_generates_new_thread_and_persists_metadata(
    client,
    thread_id: str,
):
    """流式接口遇到空字符串或纯空白 thread_id 时也应生成新会话并写入索引。"""
    store = MagicMock()
    store.save_user_message = AsyncMock()
    store.save_assistant_message = AsyncMock()

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "message": "测试流式空白线程",
                "user_id": "user1",
                "thread_id": thread_id,
            },
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0]["type"] == "mode"
    assert events[-1]["type"] == "done"
    store.save_user_message.assert_awaited_once()
    assert store.save_user_message.await_args.kwargs["thread_id"].startswith("thread_")


def test_chat_stream_customer_role_only_emits_tokens_and_done(client):
    """客服流式响应不应暴露 mode/plan/task/tool 事件。"""
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "退款怎么处理？",
            "user_id": "cust_001",
            "user_role": "customer",
            "mode": "plan",
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    events = _parse_sse_events(response.text)
    assert len(events) >= 5

    first_event = events[0]
    second_event = events[1]
    third_event = events[2]
    fourth_event = events[3]
    last_event = events[-1]

    assert first_event["type"] == "token"
    assert second_event["type"] == "token"
    assert third_event["type"] == "token"
    assert fourth_event["type"] == "token"
    assert last_event["type"] == "done"


def test_chat_stream_returns_error_event_when_attachment_oss_materialization_fails(
    client,
):
    """流式聊天在附件从 OSS 回读失败时应发 error 事件，而不是伪装成附件不存在。"""
    with patch(
        "src.api.streaming.resolve_attachment_refs_from_db",
        AsyncMock(side_effect=AttachmentStorageError("附件存储服务暂时不可用: file_sales_001")),
    ):
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "message": "帮我分析这个文件",
                "user_id": "user1",
                "attachments": [{"file_id": "file_sales_001"}],
            },
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events == [{"type": "error", "content": "文件存储服务暂时不可用，请稍后重试"}]


def test_list_conversations_returns_user_scoped_sessions(client):
    """应返回用户自己的会话列表和游标分页信息。"""
    store = MagicMock()
    store.list_by_user = AsyncMock(
        return_value={
            "items": [
                {
                    "thread_id": "thread_1",
                    "title": "三月经营复盘",
                    "channel": "web",
                    "created_at": "2026-03-20T10:00:00+08:00",
                    "last_message_at": "2026-03-20T10:05:00+08:00",
                    "message_count": 6,
                    "user_role": "门店老板",
                }
            ],
            "total": 1,
            "paging": {
                "older_cursor": "older_1",
                "newer_cursor": None,
                "has_more_older": True,
                "has_more_newer": False,
            },
        }
    )

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.get(
            "/api/v1/conversations",
            params={"user_id": "boss_001", "limit": 10, "before": "cursor_1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["thread_id"] == "thread_1"
    assert data["items"][0]["title"] == "三月经营复盘"
    assert data["paging"]["older_cursor"] == "older_1"
    store.list_by_user.assert_awaited_once_with(
        user_id="boss_001",
        limit=10,
        before="cursor_1",
        after=None,
    )


def test_rename_conversation_updates_title(client):
    """应支持重命名会话。"""
    store = MagicMock()
    store.rename = AsyncMock(
        return_value={
            "thread_id": "thread_1",
            "user_id": "boss_001",
            "title": "门店复购诊断",
            "channel": "web",
            "created_at": "2026-03-20T10:00:00+08:00",
            "last_message_at": "2026-03-20T10:05:00+08:00",
            "message_count": 6,
        }
    )

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.patch(
            "/api/v1/conversations/thread_1",
            json={"user_id": "boss_001", "title": "门店复购诊断"},
        )

    assert response.status_code == 200
    assert response.json()["title"] == "门店复购诊断"


def test_delete_conversation_soft_deletes_session(client):
    """删除会话应走软删除。"""
    store = MagicMock()
    store.soft_delete = AsyncMock(return_value=True)

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.delete(
            "/api/v1/conversations/thread_1",
            params={"user_id": "boss_001"},
        )

    assert response.status_code == 204
    store.soft_delete.assert_awaited_once_with("thread_1", "boss_001")


def test_get_conversation_reads_unified_messages(client):
    """会话详情应统一从 conversation_messages 读取。"""
    store = MagicMock()
    store.get_by_thread = AsyncMock(
        return_value={
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "title": "退款问题",
            "channel": "web",
            "created_at": "2026-03-20T12:00:00+08:00",
            "last_message_at": "2026-03-20T12:05:00+08:00",
            "message_count": 3,
            "is_deleted": False,
            "message_source": "unified",
        }
    )
    store.list_messages = AsyncMock(
        return_value={
            "items": [
                {
                    "id": "msg_1",
                    "role": "user",
                    "content": "退款怎么处理",
                    "created_at": "2026-03-20T12:00:00+08:00",
                },
                {
                    "id": "msg_2",
                    "role": "system",
                    "content": "已转人工客服，请稍候。",
                    "created_at": "2026-03-20T12:00:01+08:00",
                },
                {
                    "id": "msg_3",
                    "role": "human",
                    "content": "您好，我来继续帮您处理。",
                    "created_at": "2026-03-20T12:05:00+08:00",
                },
            ],
            "total": 3,
            "paging": {
                "older_cursor": "older_1",
                "newer_cursor": None,
                "has_more_older": True,
                "has_more_newer": False,
            },
        }
    )

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.get(
            "/api/v1/conversations/thread_customer_1",
            params={"user_id": "cust_001", "limit": 20, "before": "cursor_1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "thread_customer_1"
    assert data["messages"][0]["id"] == "msg_1"
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "system"
    assert data["messages"][2]["role"] == "human"
    assert data["paging"]["older_cursor"] == "older_1"
    store.list_messages.assert_awaited_once_with(
        thread_id="thread_customer_1",
        user_id="cust_001",
        limit=20,
        before="cursor_1",
        after=None,
    )


def test_get_conversation_rejects_legacy_session(client):
    """未迁移到统一消息表的旧会话不再提供详情。"""
    store = MagicMock()
    store.get_by_thread = AsyncMock(
        return_value={
            "thread_id": "thread_legacy_1",
            "user_id": "boss_001",
            "title": "旧会话",
            "channel": "web",
            "created_at": "2026-03-20T10:00:00+08:00",
            "last_message_at": "2026-03-20T10:05:00+08:00",
            "message_count": 6,
            "is_deleted": False,
            "message_source": "legacy",
        }
    )

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.get(
            "/api/v1/conversations/thread_legacy_1",
            params={"user_id": "boss_001"},
        )

    assert response.status_code == 404


def test_list_handoffs_returns_queue(client):
    """应暴露人工接管队列接口。"""
    response = client.get("/api/v1/handoffs", params={"status": "pending"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "handoff_1"
    assert data["items"][0]["status"] == "pending"


def test_claim_handoff_updates_status(client, mock_customer_service_store):
    """人工领取后应返回 claimed 状态。"""
    response = client.post(
        "/api/v1/handoffs/handoff_1/claim",
        json={"agent_id": "agent_a"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "claimed"
    mock_customer_service_store.claim_handoff.assert_awaited_once_with(
        handoff_id="handoff_1",
        agent_id="agent_a",
    )


def test_reply_handoff_persists_human_reply(client, mock_customer_service_store):
    """人工回复接口应写入消息并返回最新 handoff 摘要。"""
    response = client.post(
        "/api/v1/handoffs/handoff_1/reply",
        json={
            "agent_id": "agent_a",
            "content": "您好，我来继续帮您处理。",
            "resolve_after_reply": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "claimed"
    mock_customer_service_store.reply_to_handoff.assert_awaited_once_with(
        handoff_id="handoff_1",
        agent_id="agent_a",
        content="您好，我来继续帮您处理。",
        resolve_after_reply=False,
    )


def test_resolve_handoff_marks_it_completed(client, mock_customer_service_store):
    """人工结束接管后应返回 resolved 状态。"""
    response = client.post(
        "/api/v1/handoffs/handoff_1/resolve",
        json={
            "agent_id": "agent_a",
            "resolution_note": "已完成退款说明",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    mock_customer_service_store.resolve_handoff.assert_awaited_once_with(
        handoff_id="handoff_1",
        agent_id="agent_a",
        resolution_note="已完成退款说明",
    )


def test_user_profile_get(client):
    """获取用户画像"""
    with patch("src.memory.store.UserProfileStore.get_profile", AsyncMock(return_value={
        "role": "门店老板",
        "preferences": {},
        "topics": ["社群运营", "裂变活动"],
    })):
        from src.memory.store import UserProfileStore

        with patch.object(UserProfileStore, "get_profile", AsyncMock(return_value={
            "role": "门店老板",
            "preferences": {},
            "topics": ["社群运营", "裂变活动"],
        })):
            response = client.get("/api/v1/users/user123/profile")
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == "user123"
