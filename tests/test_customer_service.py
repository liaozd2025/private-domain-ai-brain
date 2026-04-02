"""客服编排器测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _import_customer_service_module():
    try:
        from src.agent.customer_service import CustomerServiceSupervisor
    except ModuleNotFoundError as exc:
        pytest.fail(f"CustomerServiceSupervisor 未实现: {exc}")
    return CustomerServiceSupervisor


class _FakeResult:
    def __init__(self, row: dict | None = None):
        self._row = row
        self.rowcount = 1

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConnection:
    def __init__(self, row: dict | None = None):
        self.row = row
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(self.row)


class _FakeAsyncContext:
    def __init__(self, connection: _FakeConnection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAsyncEngine:
    def __init__(self, row: dict | None = None):
        self.connection = _FakeConnection(row)
        self.connect_calls = 0
        self.begin_calls = 0

    def connect(self):
        self.connect_calls += 1
        return _FakeAsyncContext(self.connection)

    def begin(self):
        self.begin_calls += 1
        return _FakeAsyncContext(self.connection)


@pytest.mark.asyncio
async def test_customer_supervisor_returns_kb_answer_when_confident():
    """知识库命中时，应直接返回客服答案且不转人工。"""
    supervisor_cls = _import_customer_service_module()

    kb_agent = MagicMock()
    kb_agent.query = AsyncMock(
        return_value=SimpleNamespace(
            can_answer=True,
            content="退款申请会在 1-3 个工作日内处理完成。",
            reason="命中 customer_service 知识库",
        )
    )
    handoff_store = MagicMock()
    handoff_store.get_active_handoff = AsyncMock(return_value=None)
    handoff_store.create_or_refresh_handoff = AsyncMock()
    message_store = MagicMock()
    message_store.append_message = AsyncMock()

    supervisor = supervisor_cls(
        kb_agent=kb_agent,
        handoff_store=handoff_store,
        message_store=message_store,
    )

    result = await supervisor.invoke(
        message="退款一般多久处理完？",
        thread_id="thread_customer_1",
        user_id="cust_001",
        channel="web",
    )

    assert result.content == "退款申请会在 1-3 个工作日内处理完成。"
    kb_agent.query.assert_awaited_once()
    handoff_store.create_or_refresh_handoff.assert_not_awaited()
    assert message_store.append_message.await_count == 2


@pytest.mark.asyncio
async def test_customer_supervisor_handoffs_when_kb_cannot_answer():
    """知识库不能回答时，应自动创建人工接管。"""
    supervisor_cls = _import_customer_service_module()

    kb_agent = MagicMock()
    kb_agent.query = AsyncMock(
        return_value=SimpleNamespace(
            can_answer=False,
            content="",
            reason="未命中 customer_service 知识库",
        )
    )
    handoff_store = MagicMock()
    handoff_store.get_active_handoff = AsyncMock(return_value=None)
    handoff_store.create_or_refresh_handoff = AsyncMock(
        return_value={"id": "handoff_1", "status": "pending"}
    )
    message_store = MagicMock()
    message_store.append_message = AsyncMock()

    supervisor = supervisor_cls(
        kb_agent=kb_agent,
        handoff_store=handoff_store,
        message_store=message_store,
    )

    result = await supervisor.invoke(
        message="这个活动能不能补差价？",
        thread_id="thread_customer_2",
        user_id="cust_002",
        channel="web",
    )

    assert "已为您转接人工客服" in result.content
    handoff_store.create_or_refresh_handoff.assert_awaited_once_with(
        thread_id="thread_customer_2",
        user_id="cust_002",
        channel="web",
        reason="未命中 customer_service 知识库",
        last_customer_message="这个活动能不能补差价？",
    )
    assert message_store.append_message.await_count == 2


@pytest.mark.asyncio
async def test_customer_supervisor_suppresses_ai_when_handoff_is_active():
    """活动中的人工接管期间，不应继续触发 AI 回答。"""
    supervisor_cls = _import_customer_service_module()

    kb_agent = MagicMock()
    kb_agent.query = AsyncMock()
    handoff_store = MagicMock()
    handoff_store.get_active_handoff = AsyncMock(
        return_value={"id": "handoff_1", "status": "claimed"}
    )
    handoff_store.create_or_refresh_handoff = AsyncMock()
    message_store = MagicMock()
    message_store.append_message = AsyncMock()

    supervisor = supervisor_cls(
        kb_agent=kb_agent,
        handoff_store=handoff_store,
        message_store=message_store,
    )

    result = await supervisor.invoke(
        message="有人在处理吗？",
        thread_id="thread_customer_3",
        user_id="cust_003",
        channel="wecom",
    )

    assert "人工客服正在处理中" in result.content
    kb_agent.query.assert_not_awaited()
    handoff_store.create_or_refresh_handoff.assert_not_awaited()
    message_store.append_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_customer_service_store_append_message_commits_returning_insert():
    """客服消息 RETURNING 插入应走 begin() 提交事务，而不是 connect()。"""
    from src.memory.customer_service import CustomerServiceStore

    store = CustomerServiceStore()
    fake_engine = _FakeAsyncEngine(
        {
            "id": 1,
            "thread_id": "thread_customer_1",
            "user_id": "cust_001",
            "channel": "web",
            "sender_type": "unknown",
            "content": "仅测试事务提交",
            "created_at": "2026-03-24T10:00:00+08:00",
        }
    )
    store._engine = fake_engine
    store._ensure_schema = AsyncMock(return_value=True)

    result = await store.append_message(
        thread_id="thread_customer_1",
        user_id="cust_001",
        channel="web",
        sender_type="unknown",
        content="仅测试事务提交",
    )

    assert result["thread_id"] == "thread_customer_1"
    assert fake_engine.connect_calls == 0
    assert fake_engine.begin_calls == 1
