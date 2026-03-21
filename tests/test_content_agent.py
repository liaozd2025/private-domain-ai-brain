"""内容生成子智能体测试"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.mark.asyncio
async def test_content_agent_generates_text(mock_llm):
    """内容生成 Agent 应返回非空文本"""
    from src.subagents.content_generation import ContentGenerationAgent

    agent_mock = AsyncMock()
    agent_mock.ainvoke = AsyncMock(return_value={"output": "🌟 周末限定！买一送一..."})

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


def test_content_agent_system_prompt_loads_skill_assets():
    """内容生成 prompt 应从 skill 文档加载专用规则和共享私域知识。"""
    from src.subagents.content_generation import build_content_generation_system_prompt

    prompt = build_content_generation_system_prompt()

    assert "内容生成技能规范" in prompt
    assert "私域运营领域知识" in prompt
    assert "小红书笔记" in prompt
    assert "私域 GMV" in prompt
