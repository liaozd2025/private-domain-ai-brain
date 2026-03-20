"""API 端点集成测试"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


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
                {"content": "分析当前数据", "status": "in_progress"},
                {"content": "制定执行动作", "status": "pending"},
            ],
        }
        yield {"type": "token", "content": "计"}
        yield {"type": "token", "content": "划"}
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


def test_health_check(client):
    """健康检查端点应返回 ok"""
    with patch("src.memory.checkpointer.get_checkpointer", AsyncMock()):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


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


def test_chat_generates_thread_id(client):
    """不传 thread_id 时应自动生成"""
    response = client.post(
        "/api/v1/chat",
        json={"message": "测试", "user_id": "user1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"].startswith("thread_")


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


def test_chat_creates_conversation_metadata(client, mock_orchestrator):
    """聊天成功后应创建/更新会话元数据。"""
    store = MagicMock()
    store.upsert_on_turn = AsyncMock()

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
    store.upsert_on_turn.assert_awaited_once()
    kwargs = store.upsert_on_turn.await_args.kwargs
    assert kwargs["thread_id"] == "thread_meta_1"
    assert kwargs["user_id"] == "boss_001"
    assert kwargs["message"] == "帮我分析一下本月门店经营"
    assert kwargs["channel"] == "web"


def test_chat_empty_message(client):
    """空消息应返回 422"""
    response = client.post(
        "/api/v1/chat",
        json={"message": "", "user_id": "user1"},
    )
    assert response.status_code == 422


def test_file_upload(client, tmp_path):
    """文件上传测试"""
    # 创建测试文件
    test_file = tmp_path / "test.csv"
    test_file.write_text("名称,销售额\n门店A,10000\n门店B,20000")

    with patch("src.config.settings.upload_dir", str(tmp_path)):
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

    with patch("src.config.settings.upload_dir", str(tmp_path)):
        response = client.post(
            "/api/v1/files/upload",
            files={"file": ("poster.png", open(test_file, "rb"), "image/png")},
            data={"user_id": "user1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "poster.png"
    assert data["file_type"] == "image"


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
    """聊天请求只传 file_id 时，服务端应解析出完整附件信息"""
    test_file = tmp_path / "sales.csv"
    test_file.write_text("门店,销售额\nA,100\nB,200", encoding="utf-8")

    with patch("src.config.settings.upload_dir", str(tmp_path)):
        upload_response = client.post(
            "/api/v1/files/upload",
            files={"file": ("sales.csv", open(test_file, "rb"), "text/csv")},
            data={"user_id": "user1"},
        )
        assert upload_response.status_code == 200
        file_id = upload_response.json()["file_id"]

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
    assert attachments[0]["file_path"].endswith(".csv")


def test_chat_rejects_unknown_attachment_id(client):
    """未知附件 ID 应返回 400"""
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "帮我看看这个文件",
            "user_id": "user1",
            "attachments": [{"file_id": "missing-file-id"}],
        },
    )
    assert response.status_code == 400


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
    assert "plan" in data
    assert isinstance(data["plan"], list)
    assert data["content"] == "这是 plan 模式的回答。"


def test_chat_stream_plan_mode_emits_plan_event_first(client):
    """plan 模式流式接口应先发送计划事件，再进入执行阶段"""
    with client.websocket_connect("/api/v1/chat/stream") as websocket:
        websocket.send_json(
            {
                "message": "先规划再执行一份门店活动方案",
                "user_id": "planner_ws",
                "mode": "plan",
            }
        )

        first_event = websocket.receive_json()
        assert first_event["type"] == "plan"
        assert isinstance(first_event["content"], list)


def test_list_conversations_returns_user_scoped_sessions(client):
    """应返回用户自己的会话列表。"""
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
                }
            ],
            "total": 1,
        }
    )

    with patch("src.memory.conversations.get_conversation_store", return_value=store):
        response = client.get("/api/v1/conversations", params={"user_id": "boss_001"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["thread_id"] == "thread_1"
    assert data["items"][0]["title"] == "三月经营复盘"


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
