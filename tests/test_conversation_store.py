"""会话元数据存储测试"""

from unittest.mock import AsyncMock

import pytest


def test_build_conversation_title_uses_first_message_preview():
    """标题应取首条消息摘要并裁剪。"""
    from src.memory.conversations import build_conversation_title

    title = build_conversation_title(
        "  请帮我分析一下三月份门店复购率下降的原因，并给出改进建议。  "
    )

    assert title == "请帮我分析一下三月份门店复购率下降的原因，并给出改进建议。"


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
async def test_upsert_new_conversation_sets_initial_metadata():
    """新会话 upsert 应写入标题、渠道和消息数。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    store._execute = AsyncMock(return_value="EXECUTED")
    store._write_fetchrow = AsyncMock(
        return_value={
            "thread_id": "thread_1",
            "user_id": "boss_001",
            "title": "三月经营复盘",
            "channel": "web",
            "created_at": "2026-03-20T10:00:00+08:00",
            "last_message_at": "2026-03-20T10:05:00+08:00",
            "message_count": 2,
            "is_deleted": False,
            "deleted_at": None,
        }
    )

    result = await store.upsert_on_turn(
        thread_id="thread_1",
        user_id="boss_001",
        message="三月经营复盘",
        channel="web",
    )

    assert result["thread_id"] == "thread_1"
    assert result["message_count"] == 2
    assert result["title"] == "三月经营复盘"


@pytest.mark.asyncio
async def test_soft_deleted_conversation_can_be_restored_on_new_turn():
    """已软删除会话收到新消息后应恢复。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    store._execute = AsyncMock(return_value="EXECUTED")
    store._write_fetchrow = AsyncMock(
        return_value={
            "thread_id": "thread_1",
            "user_id": "boss_001",
            "title": "旧标题",
            "channel": "web",
            "created_at": "2026-03-20T10:00:00+08:00",
            "last_message_at": "2026-03-20T10:06:00+08:00",
            "message_count": 4,
            "is_deleted": False,
            "deleted_at": None,
        }
    )

    result = await store.upsert_on_turn(
        thread_id="thread_1",
        user_id="boss_001",
        message="继续这个话题",
        channel="web",
    )

    assert result["is_deleted"] is False


@pytest.mark.asyncio
async def test_record_messages_writes_unified_rows_and_updates_metadata():
    """统一消息写入应在单一事务中落明细表和会话索引。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    fake_engine = _FakeAsyncEngine(
        {
            "thread_id": "thread_1",
            "user_id": "boss_001",
            "user_role": "门店老板",
            "title": "三月经营复盘",
            "channel": "web",
            "created_at": "2026-03-23T10:00:00+08:00",
            "last_message_at": "2026-03-23T10:05:00+08:00",
            "message_count": 2,
            "is_deleted": False,
            "deleted_at": None,
            "message_source": "unified",
        }
    )
    store._engine = fake_engine
    store._ensure_schema = AsyncMock(return_value=True)

    result = await store.record_messages(
        thread_id="thread_1",
        user_id="boss_001",
        user_role="门店老板",
        channel="web",
        store_id="store_001",
        messages=[
            {"role": "user", "content": "帮我分析本月经营"},
            {"role": "assistant", "content": "这是分析结果"},
        ],
    )

    assert result["thread_id"] == "thread_1"
    assert result["message_source"] == "unified"
    # 所有写入在同一事务内完成
    assert fake_engine.begin_calls == 1
    assert fake_engine.connect_calls == 0
    # 共执行 3 条 SQL：2条消息 INSERT + 1条 metadata UPSERT
    assert len(fake_engine.connection.statements) == 3


@pytest.mark.asyncio
async def test_record_messages_commits_metadata_upsert_with_transaction():
    """带 RETURNING 的 metadata upsert 应走 begin() 提交事务，而不是 connect()。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    fake_engine = _FakeAsyncEngine(
        {
            "thread_id": "thread_1",
            "user_id": "boss_001",
            "user_role": "门店老板",
            "title": "帮我分析本月经营",
            "channel": "web",
            "created_at": "2026-03-24T10:00:00+08:00",
            "last_message_at": "2026-03-24T10:05:00+08:00",
            "message_count": 2,
            "message_source": "unified",
            "is_deleted": False,
            "deleted_at": None,
        }
    )
    store._engine = fake_engine
    store._ensure_schema = AsyncMock(return_value=True)

    result = await store.record_messages(
        thread_id="thread_1",
        user_id="boss_001",
        user_role="门店老板",
        channel="web",
        store_id="store_001",
        messages=[
            {"role": "user", "content": "帮我分析本月经营"},
            {"role": "assistant", "content": "这是分析结果"},
        ],
    )

    assert result["thread_id"] == "thread_1"
    assert fake_engine.connect_calls == 0
    assert fake_engine.begin_calls == 1


@pytest.mark.asyncio
async def test_list_by_user_filters_to_unified_sessions_and_returns_paging():
    """会话列表应只返回统一消息模型，并携带分页游标。"""
    from src.memory.conversations import ConversationStore, _encode_cursor

    store = ConversationStore()
    store._fetch = AsyncMock(
        side_effect=[
            [
                {
                    "thread_id": "thread_2",
                    "user_id": "boss_001",
                    "user_role": "门店老板",
                    "title": "最新会话",
                    "channel": "web",
                    "created_at": "2026-03-23T10:00:00+08:00",
                    "last_message_at": "2026-03-23T10:05:00+08:00",
                    "message_count": 4,
                    "is_deleted": False,
                    "deleted_at": None,
                    "message_source": "unified",
                }
            ],
            [],
            [],
        ]
    )
    store._fetchrow = AsyncMock(return_value={"total": 1})
    before_cursor = _encode_cursor(
        {
            "last_message_at": "2026-03-23T09:59:00+08:00",
            "thread_id": "thread_1",
        }
    )

    result = await store.list_by_user(
        user_id="boss_001",
        limit=20,
        before=before_cursor,
        after=None,
    )

    assert result["items"][0]["thread_id"] == "thread_2"
    assert result["paging"]["older_cursor"] is not None
    first_stmt = store._fetch.await_args_list[0].args[0]
    assert not isinstance(first_stmt, str)
    assert "conversation_metadata" in str(first_stmt)


@pytest.mark.asyncio
async def test_list_messages_returns_latest_page_in_ascending_order():
    """详情默认取最新一页，但返回顺序应保持旧到新。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    store._fetch = AsyncMock(
        side_effect=[
            [
                {
                    "id": 3,
                    "thread_id": "thread_1",
                    "user_id": "boss_001",
                    "channel": "web",
                    "store_id": "store_001",
                    "role": "assistant",
                    "content": "最新回复",
                    "created_at": "2026-03-23T10:05:00+08:00",
                },
                {
                    "id": 2,
                    "thread_id": "thread_1",
                    "user_id": "boss_001",
                    "channel": "web",
                    "store_id": "store_001",
                    "role": "user",
                    "content": "继续分析",
                    "created_at": "2026-03-23T10:04:00+08:00",
                },
            ],
            [],
            [],
        ]
    )
    store._fetchrow = AsyncMock(return_value={"total": 3})

    result = await store.list_messages(
        thread_id="thread_1",
        user_id="boss_001",
        limit=2,
        before=None,
        after=None,
    )

    first_stmt = store._fetch.await_args_list[0].args[0]
    assert not isinstance(first_stmt, str)
    assert "conversation_messages" in str(first_stmt)
    assert [item["id"] for item in result["items"]] == ["2", "3"]
    assert result["items"][0]["content"] == "继续分析"
    assert result["total"] == 3
