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


@pytest.mark.asyncio
async def test_upsert_new_conversation_sets_initial_metadata():
    """新会话 upsert 应写入标题、渠道和消息数。"""
    from src.memory.conversations import ConversationStore

    store = ConversationStore()
    store._execute = AsyncMock(return_value="EXECUTED")
    store._fetchrow = AsyncMock(
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
    store._fetchrow = AsyncMock(
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
