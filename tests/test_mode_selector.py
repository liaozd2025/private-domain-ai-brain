"""自动模式选择器测试"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_explicit_mode_bypasses_auto_selection():
    """显式 mode 应直接返回，不再自动判断。"""
    from src.agent.mode_selector import ModeSelector

    llm = MagicMock()
    selector = ModeSelector(llm)

    decision = await selector.resolve_mode(
        message="先规划再执行活动方案",
        requested_mode="chat",
    )

    assert decision["requested_mode"] == "chat"
    assert decision["resolved_mode"] == "chat"
    assert decision["selection_source"] == "explicit"


@pytest.mark.asyncio
async def test_auto_mode_uses_heuristic_for_planning_requests():
    """明显的规划执行请求应通过规则进入 plan。"""
    from src.agent.mode_selector import ModeSelector

    llm = MagicMock()
    selector = ModeSelector(llm)

    decision = await selector.resolve_mode(
        message="先规划再执行一份门店活动方案",
        requested_mode="auto",
    )

    assert decision["resolved_mode"] == "plan"
    assert decision["selection_source"] == "heuristic"


@pytest.mark.asyncio
async def test_auto_mode_falls_back_to_chat_on_llm_failure():
    """自动选择失败时应保守降级到 chat。"""
    from src.agent.mode_selector import ModeSelector

    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=RuntimeError("selector llm failed")
    )
    selector = ModeSelector(llm)

    decision = await selector.resolve_mode(
        message="这个月会员活跃度为什么下降",
        requested_mode="auto",
    )

    assert decision["resolved_mode"] == "chat"
    assert decision["selection_source"] == "fallback"
