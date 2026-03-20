"""内容生成子智能体测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.mark.asyncio
async def test_content_agent_generates_text(mock_llm):
    """内容生成 Agent 应返回非空文本"""
    from src.subagents.content_generation import ContentGenerationAgent

    agent_mock = AsyncMock()
    agent_mock.ainvoke = AsyncMock(return_value={"output": "🌟 周末限定！买一送一..."})

    with patch("src.subagents.content_generation.AgentExecutor", return_value=agent_mock):
        with patch("src.subagents.content_generation.create_tool_calling_agent", return_value=MagicMock()):
            agent = ContentGenerationAgent(llm=mock_llm)
            agent._agent = agent_mock

            result = await agent.generate("帮我写一个朋友圈文案")
            assert isinstance(result, str)
            assert len(result) > 0


@pytest.mark.asyncio
async def test_content_agent_role_and_channel_injected(mock_llm):
    """内容生成应将角色和渠道注入请求"""
    from src.subagents.content_generation import ContentGenerationAgent

    captured = {}

    async def capture(args):
        captured.update(args)
        return {"output": "内容"}

    agent_mock = AsyncMock()
    agent_mock.ainvoke = AsyncMock(side_effect=capture)

    with patch("src.subagents.content_generation.AgentExecutor", return_value=agent_mock):
        with patch("src.subagents.content_generation.create_tool_calling_agent", return_value=MagicMock()):
            agent = ContentGenerationAgent(llm=mock_llm)
            agent._agent = agent_mock

            await agent.generate("写个文案", user_role="销售", channel="moments")
            assert "销售" in captured["input"]
            assert "moments" in captured["input"]


def test_content_tools_load_template():
    """load_template 应返回模板框架"""
    from src.tools.content_tools import load_template

    result = load_template.invoke({"template_type": "朋友圈文案"})
    assert "朋友圈文案" in result
    assert "结构" in result


def test_content_tools_unknown_template():
    """未知模板应返回可用模板列表"""
    from src.tools.content_tools import load_template

    result = load_template.invoke({"template_type": "不存在的模板"})
    assert "可用模板" in result


def test_get_platform_rules():
    """平台规则应返回对应规则"""
    from src.tools.content_tools import get_platform_rules

    result = get_platform_rules.invoke({"platform": "wecom"})
    assert "企业微信" in result

    result_unknown = get_platform_rules.invoke({"platform": "unknown_platform"})
    assert "可用平台" in result_unknown
