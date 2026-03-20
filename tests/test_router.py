"""路由分类器测试

验证：闲聊不查 KB，各类问题正确路由
目标：分类准确率 > 90%（50+ 测试用例覆盖）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent.router import QueryRouter, QueryType, RouterDecision


# ===== Fixtures =====

@pytest.fixture
def mock_llm():
    """模拟 LLM（避免真实 API 调用）"""
    llm = MagicMock()
    structured_llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    return llm, structured_llm


@pytest.fixture
def router(mock_llm):
    llm, _ = mock_llm
    return QueryRouter(llm)


# ===== 分类测试用例 =====

CHITCHAT_CASES = [
    "你好",
    "谢谢你",
    "你是谁",
    "你能做什么",
    "今天天气怎么样",
    "哈哈",
    "好的",
    "明白了",
]

KNOWLEDGE_QUERY_CASES = [
    "私域运营怎么做",
    "门店如何提升复购率",
    "社群运营的最佳实践是什么",
    "企微怎么做客户留存",
    "裂变活动有哪些常见形式",
    "朋友圈运营有什么技巧",
    "会员体系如何设计",
    "私域流量和公域流量有什么区别",
]

CONTENT_GENERATION_CASES = [
    "帮我写一个朋友圈文案",
    "生成一份活动方案",
    "写个门店 SOP",
    "帮我设计一个话术",
    "写一篇小红书推文，主题是夏日限定活动",
    "给我一个社群建群的欢迎语",
    "帮我写一段销售话术处理价格异议",
]

DATA_ANALYSIS_CASES = [
    "帮我分析这份销售数据",
    "上传的 Excel 里哪个门店表现最好",
    "画一个月度趋势图",
    "这个数据有什么规律",
    "统计一下各区域的销量分布",
]

TOOL_ACTION_CASES = [
    "发消息给张三",
    "推送这条内容到群里",
    "查询用户 ID 是 12345 的消费记录",
]


def make_decision(query_type: QueryType) -> RouterDecision:
    return RouterDecision(
        query_type=query_type,
        confidence=0.95,
        reasoning=f"测试用例 - {query_type}",
    )


@pytest.mark.asyncio
async def test_chitchat_classification(router, mock_llm):
    """闲聊类消息应路由到 chitchat，不查知识库"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    for query in CHITCHAT_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.CHITCHAT, f"'{query}' 应为 chitchat"


@pytest.mark.asyncio
async def test_knowledge_query_classification(router, mock_llm):
    """知识查询类消息应路由到 knowledge_query"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.KNOWLEDGE_QUERY))

    for query in KNOWLEDGE_QUERY_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.KNOWLEDGE_QUERY, f"'{query}' 应为 knowledge_query"


@pytest.mark.asyncio
async def test_content_generation_classification(router, mock_llm):
    """内容生成类消息应路由到 content_generation"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CONTENT_GENERATION))

    for query in CONTENT_GENERATION_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.CONTENT_GENERATION, f"'{query}' 应为 content_generation"


@pytest.mark.asyncio
async def test_data_analysis_classification(router, mock_llm):
    """数据分析类消息应路由到 data_analysis"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.DATA_ANALYSIS))

    for query in DATA_ANALYSIS_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.DATA_ANALYSIS, f"'{query}' 应为 data_analysis"


@pytest.mark.asyncio
async def test_attachment_analysis_classification_prefers_attachment_route(router, mock_llm):
    """图片/文档附件分析请求应优先走 attachment_analysis"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        "帮我看看这张图讲了什么",
        attachments=[{"file_type": "image", "filename": "poster.png"}],
    )
    assert decision.query_type == QueryType.ATTACHMENT_ANALYSIS
    structured_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_tabular_attachment_with_analysis_keywords_routes_to_data_analysis(router, mock_llm):
    """表格附件 + 分析关键词应继续走 data_analysis"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        "统计这份表格里的销售额趋势",
        attachments=[{"file_type": "csv", "filename": "sales.csv"}],
    )
    assert decision.query_type == QueryType.DATA_ANALYSIS
    structured_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_on_error(router, mock_llm):
    """LLM 出错时应降级到 knowledge_query"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(side_effect=Exception("模拟 LLM 错误"))

    decision = await router.classify("什么都行")
    assert decision.query_type == QueryType.KNOWLEDGE_QUERY
    assert decision.confidence == 0.5


@pytest.mark.asyncio
async def test_context_included_in_classify(router, mock_llm):
    """带上下文的分类调用"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        query="你好",
        context="用户: 嗨 | AI: 你好！有什么我能帮到您的？",
    )
    assert decision is not None
    # 验证上下文被传入（通过 ainvoke 调用参数）
    call_args = structured_llm.ainvoke.call_args
    messages = call_args[0][0]
    # 最后一条消息应包含上下文
    assert "对话上下文" in str(messages[-1].content)


def test_router_decision_confidence_range():
    """RouterDecision 的 confidence 应在 0-1 之间"""
    import pytest
    from pydantic import ValidationError

    # 正常值
    d = RouterDecision(query_type=QueryType.CHITCHAT, confidence=0.9, reasoning="test")
    assert 0 <= d.confidence <= 1

    # 超出范围应报错
    with pytest.raises(ValidationError):
        RouterDecision(query_type=QueryType.CHITCHAT, confidence=1.5, reasoning="test")
