"""KB 子智能体测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    return llm


@pytest.mark.asyncio
async def test_kb_agent_returns_answer(mock_llm):
    """KB Agent 应返回字符串答案"""
    with patch("src.subagents.knowledge_base.KB_TOOLS", []):
        from src.subagents.knowledge_base import KBAgent

        agent_executor_mock = AsyncMock()
        agent_executor_mock.ainvoke = AsyncMock(
            return_value={"output": "这是一个关于私域运营的知识库答案 [1] 参考文档"}
        )

        with patch("src.subagents.knowledge_base.AgentExecutor", return_value=agent_executor_mock):
            with patch("src.subagents.knowledge_base.create_tool_calling_agent", return_value=MagicMock()):
                kb = KBAgent(llm=mock_llm)
                kb._agent = agent_executor_mock

                result = await kb.query("私域运营怎么做")
                assert isinstance(result, str)
                assert len(result) > 0


@pytest.mark.asyncio
async def test_kb_agent_handles_error(mock_llm):
    """KB Agent 出错时返回友好错误信息"""
    with patch("src.subagents.knowledge_base.KB_TOOLS", []):
        from src.subagents.knowledge_base import KBAgent

        agent_executor_mock = AsyncMock()
        agent_executor_mock.ainvoke = AsyncMock(side_effect=Exception("模拟错误"))

        with patch("src.subagents.knowledge_base.AgentExecutor", return_value=agent_executor_mock):
            with patch("src.subagents.knowledge_base.create_tool_calling_agent", return_value=MagicMock()):
                kb = KBAgent(llm=mock_llm)
                kb._agent = agent_executor_mock

                result = await kb.query("测试查询")
                assert "失败" in result or "错误" in result


@pytest.mark.asyncio
async def test_kb_agent_role_injection(mock_llm):
    """KB Agent 应将用户角色注入查询"""
    with patch("src.subagents.knowledge_base.KB_TOOLS", []):
        from src.subagents.knowledge_base import KBAgent

        captured_input = {}

        async def capture_input(args):
            captured_input.update(args)
            return {"output": "测试答案"}

        agent_executor_mock = AsyncMock()
        agent_executor_mock.ainvoke = AsyncMock(side_effect=capture_input)

        with patch("src.subagents.knowledge_base.AgentExecutor", return_value=agent_executor_mock):
            with patch("src.subagents.knowledge_base.create_tool_calling_agent", return_value=MagicMock()):
                kb = KBAgent(llm=mock_llm)
                kb._agent = agent_executor_mock

                await kb.query("私域运营怎么做", user_role="门店老板")
                assert "门店老板" in captured_input.get("input", "")
