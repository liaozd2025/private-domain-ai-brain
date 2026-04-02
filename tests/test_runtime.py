"""运行时适配层测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError


def test_extract_text_from_state_prefers_last_non_empty_ai_message():
    """尾部空白 AI tool-call 消息不应覆盖前面已有的有效回答。"""
    from src.agent.runtime import extract_text_from_state

    result = {
        "messages": [
            HumanMessage(content="帮我分析附件"),
            AIMessage(content="最终分析报告"),
            AIMessage(content="\n\n\n"),
        ]
    }

    assert extract_text_from_state(result) == "最终分析报告"


def test_extract_last_ai_text_ignores_human_message_fallback():
    """递归兜底只应回收 AI 已产出的文本。"""
    from src.agent.runtime import extract_last_ai_text

    result = {
        "messages": [
            HumanMessage(content="帮我分析附件"),
            AIMessage(content="\n\n\n"),
        ]
    }

    assert extract_last_ai_text(result) == ""


@pytest.mark.asyncio
async def test_modern_tool_agent_returns_partial_output_on_graph_recursion_error():
    """出现递归上限时，如果已经有有效 AI 文本，应直接回传而不是抛错。"""
    from src.agent.runtime import ModernToolAgent

    class _FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {
                "messages": [
                    HumanMessage(content="帮我分析附件"),
                    AIMessage(content="阶段性分析结果"),
                    AIMessage(content="\n\n\n"),
                ]
            }
            raise GraphRecursionError("recursion limit reached")

    with patch("src.agent.runtime.create_agent", return_value=_FakeAgent()):
        agent = ModernToolAgent(
            llm=MagicMock(),
            tools=[],
            system_prompt="test",
        )

    result = await agent.ainvoke({"input": "帮我分析附件"})

    assert result == {"output": "阶段性分析结果"}


@pytest.mark.asyncio
async def test_modern_tool_agent_re_raises_graph_recursion_error_without_partial_output():
    """如果递归上限前没有任何有效文本，仍应抛出原异常。"""
    from src.agent.runtime import ModernToolAgent

    class _FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {"messages": [HumanMessage(content="帮我分析附件"), AIMessage(content="\n\n\n")]}
            raise GraphRecursionError("recursion limit reached")

    with patch("src.agent.runtime.create_agent", return_value=_FakeAgent()):
        agent = ModernToolAgent(
            llm=MagicMock(),
            tools=[],
            system_prompt="test",
        )

    with pytest.raises(GraphRecursionError):
        await agent.ainvoke({"input": "帮我分析附件"})
