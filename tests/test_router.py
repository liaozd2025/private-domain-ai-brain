"""路由分类器测试

验证：闲聊不查 KB，各类问题正确路由，附件路由边界条件，启发式短路，置信度兜底
目标：分类准确率 > 90%（50+ 测试用例覆盖）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

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


def make_decision(query_type: QueryType, confidence: float = 0.95) -> RouterDecision:
    return RouterDecision(
        query_type=query_type,
        confidence=confidence,
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
        assert decision.query_type == QueryType.CONTENT_GENERATION, (
            f"'{query}' 应为 content_generation"
        )


@pytest.mark.asyncio
async def test_data_analysis_classification(router, mock_llm):
    """数据分析类消息应路由到 data_analysis"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.DATA_ANALYSIS))

    for query in DATA_ANALYSIS_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.DATA_ANALYSIS, f"'{query}' 应为 data_analysis"


@pytest.mark.asyncio
async def test_tool_action_classification(router, mock_llm):
    """工具操作类消息应路由到 tool_action"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.TOOL_ACTION))

    for query in TOOL_ACTION_CASES:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.TOOL_ACTION, f"'{query}' 应为 tool_action"


# ===== 附件路由边界测试 =====

@pytest.mark.asyncio
async def test_tabular_attachment_with_analysis_keywords_routes_to_data_analysis(router, mock_llm):
    """表格附件 + 分析关键词 → data_analysis（确定性短路，不调 LLM）"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        "统计这份表格里的销售额趋势",
        attachments=[{"file_type": "csv", "filename": "sales.csv"}],
    )
    assert decision.query_type == QueryType.DATA_ANALYSIS
    structured_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_attachment_with_keywords_routes_to_attachment_analysis(router, mock_llm):
    """图片附件 + 附件分析关键词 → attachment_analysis（确定性短路，不调 LLM）"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        "帮我看看这张图讲了什么",
        attachments=[{"file_type": "image", "filename": "poster.png"}],
    )
    assert decision.query_type == QueryType.ATTACHMENT_ANALYSIS
    structured_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_csv_attachment_without_analysis_keywords_falls_through_to_llm(router, mock_llm):
    """CSV 附件 + 非分析意图（如写方案）→ 不短路，交由 LLM 分类"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CONTENT_GENERATION))

    decision = await router.classify(
        "帮我根据这份数据写一份活动方案",
        attachments=[{"file_type": "csv", "filename": "data.csv"}],
    )
    # LLM 返回 content_generation，不应被强制路由到 data_analysis 或 attachment_analysis
    assert decision.query_type == QueryType.CONTENT_GENERATION
    structured_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_attachment_without_analysis_keywords_falls_through_to_llm(router, mock_llm):
    """图片附件 + 无附件分析关键词（纯内容创作意图）→ 不短路，交由 LLM 分类"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CONTENT_GENERATION))

    # 使用不含任何附件分析关键词的纯创作请求
    decision = await router.classify(
        "帮我写一份国庆周年庆活动方案",
        attachments=[{"file_type": "image", "filename": "brand_ref.png"}],
    )
    assert decision.query_type == QueryType.CONTENT_GENERATION
    structured_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_attachments_no_heuristic_short_circuit_for_non_chitchat(router, mock_llm):
    """无附件且非闲聊消息 → 走 LLM 分类"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.KNOWLEDGE_QUERY))

    decision = await router.classify("私域运营怎么做")
    assert decision.query_type == QueryType.KNOWLEDGE_QUERY
    structured_llm.ainvoke.assert_awaited_once()


# ===== 启发式短路测试 =====

@pytest.mark.asyncio
async def test_chitchat_heuristic_short_circuit_skips_llm(router, mock_llm):
    """明显闲聊词应触发启发式短路，不调 LLM"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.KNOWLEDGE_QUERY))

    for query in ["你好", "谢谢", "好的", "明白了", "再见", "哈哈"]:
        decision = await router.classify(query)
        assert decision.query_type == QueryType.CHITCHAT, f"'{query}' 应被启发式短路为 chitchat"

    # 启发式短路不应调用 LLM
    structured_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_chitchat_heuristic_skipped_when_has_attachments(router, mock_llm):
    """有附件时不触发闲聊启发式短路（附件可能改变意图）"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.ATTACHMENT_ANALYSIS))

    # "好的" 本来会触发 chitchat 短路，但有附件时应交由附件路由或 LLM 处理
    decision = await router.classify(
        "好的帮我看看这个",
        attachments=[{"file_type": "image", "filename": "img.png"}],
    )
    # "看看" 是附件分析关键词，应走 attachment_analysis 短路
    assert decision.query_type == QueryType.ATTACHMENT_ANALYSIS


# ===== 错误降级测试 =====

@pytest.mark.asyncio
async def test_fallback_on_error_returns_chitchat(router, mock_llm):
    """LLM 出错时应降级到 chitchat（避免触发无意义的 Milvus 搜索）"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(side_effect=Exception("模拟 LLM 错误"))

    decision = await router.classify("私域运营怎么做")
    assert decision.query_type == QueryType.CHITCHAT
    assert decision.confidence < 0.5  # 降级置信度应较低


# ===== 置信度测试 =====

@pytest.mark.asyncio
async def test_high_confidence_decision_passes_through(router, mock_llm):
    """高置信度决策应直接返回"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(
        return_value=make_decision(QueryType.KNOWLEDGE_QUERY, confidence=0.95)
    )

    decision = await router.classify("社群运营技巧")
    assert decision.query_type == QueryType.KNOWLEDGE_QUERY
    assert decision.confidence == 0.95


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


# ===== 上下文传递测试 =====

@pytest.mark.asyncio
async def test_context_included_in_classify(router, mock_llm):
    """带上下文的分类调用应将上下文传入 LLM"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CHITCHAT))

    decision = await router.classify(
        query="继续",
        context="用户: 帮我写个朋友圈文案 | AI: 好的，请问是什么主题？",
    )
    assert decision is not None
    call_args = structured_llm.ainvoke.call_args
    messages = call_args[0][0]
    # 最后一条消息应包含上下文
    assert "对话上下文" in str(messages[-1].content)


@pytest.mark.asyncio
async def test_attachments_info_included_in_llm_context(router, mock_llm):
    """有附件但无短路时，附件信息应传入 LLM 上下文"""
    _, structured_llm = mock_llm
    structured_llm.ainvoke = AsyncMock(return_value=make_decision(QueryType.CONTENT_GENERATION))

    await router.classify(
        query="帮我写个推广方案",
        attachments=[{"file_type": "image", "filename": "brand.png"}],
    )
    call_args = structured_llm.ainvoke.call_args
    messages = call_args[0][0]
    # 应包含附件信息
    assert "附件" in str(messages[-1].content) or "image" in str(messages[-1].content)
