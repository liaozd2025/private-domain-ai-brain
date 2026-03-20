"""查询路由/分类器 - 将用户请求分类为 5 种意图类型

核心设计：集成在编排器 system prompt 中，不额外增加 LLM 调用。
路由决策通过结构化输出（Pydantic）从 LLM 响应中提取。
"""

from enum import Enum
from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class QueryType(str, Enum):
    """查询类型枚举 - 5 大类意图"""
    CHITCHAT = "chitchat"                    # 闲聊/问候/简单对话 → 直接回答
    KNOWLEDGE_QUERY = "knowledge_query"      # 知识查询 → KB Agent
    DATA_ANALYSIS = "data_analysis"         # 数据分析 → Data Agent
    CONTENT_GENERATION = "content_generation"  # 内容生成 → Content Agent
    TOOL_ACTION = "tool_action"             # 工具操作 → OpenClaw
    ATTACHMENT_ANALYSIS = "attachment_analysis"  # 图片/文档/混合附件分析


class RouterDecision(BaseModel):
    """路由决策结构"""
    query_type: QueryType = Field(description="查询类型")
    confidence: float = Field(ge=0.0, le=1.0, description="分类置信度")
    reasoning: str = Field(description="分类理由（简短）")
    sub_intent: Optional[str] = Field(default=None, description="子意图（可选细分）")


# 路由系统 Prompt - 内嵌在编排器中使用
ROUTER_SYSTEM_PROMPT = """你是一个查询意图分类器。将用户消息分类为以下 5 类之一：

## 分类规则

**chitchat** - 闲聊、问候、感谢、随意聊天、简单询问
- 例："你好"、"谢谢"、"你是谁"、"今天天气怎样"、"你能做什么"

**knowledge_query** - 需要查阅专业知识库的问题
- 例："私域运营怎么做"、"门店如何提升复购率"、"社群运营的最佳实践是什么"
- 涉及：私域运营策略、行业知识、操作规程、政策文件等需要在知识库中查找的问题

**data_analysis** - 需要分析数据、处理文件、生成图表的任务
- 例："帮我分析这份销售数据"、"上传的 Excel 里哪个门店表现最好"、"画一个月度趋势图"
- 通常伴随文件上传，或包含"分析"、"统计"、"图表"、"报表"等关键词

**content_generation** - 需要生成、创作、撰写内容的任务
- 例："帮我写一个朋友圈文案"、"生成一份活动方案"、"写个门店 SOP"、"设计一个话术"
- 包含：文案、方案、SOP、话术、海报文字、推文、公告等创作任务

**tool_action** - 需要执行具体操作的任务
- 例："发消息给客户 xxx"、"查询某个用户的记录"、"推送这条内容"

**attachment_analysis** - 用户已上传图片或文档，要求理解、总结、提取信息
- 例："帮我看看这张海报讲了什么"、"总结这个 PDF"、"识别这张截图里的关键信息"

## 输出要求
严格按 JSON 格式输出，包含：query_type、confidence（0-1）、reasoning（一句话）、sub_intent（可选）
"""

TABULAR_FILE_TYPES = {"csv", "excel"}
ATTACHMENT_ANALYSIS_KEYWORDS = {
    "图片", "图", "截图", "海报", "照片", "文件", "文档",
    "总结", "摘要", "提取", "识别", "看看", "分析", "讲了什么",
}
TABLE_ANALYSIS_KEYWORDS = {
    "分析", "统计", "图表", "趋势", "报表", "对比", "汇总",
    "销售额", "订单", "占比", "分布", "最高", "最低", "均值",
}


class QueryRouter:
    """查询路由器 - 使用 LLM 进行意图分类"""

    def __init__(self, llm):
        self.llm = llm
        self._structured_llm = llm.with_structured_output(RouterDecision)

    def _classify_with_attachments(
        self,
        query: str,
        attachments: list[dict] | None = None,
    ) -> RouterDecision | None:
        """附件优先路由规则"""
        if not attachments:
            return None

        file_types = {a.get("file_type", "").lower() for a in attachments}
        query_text = query.strip().lower()

        if file_types & TABULAR_FILE_TYPES and any(keyword in query_text for keyword in TABLE_ANALYSIS_KEYWORDS):
            return RouterDecision(
                query_type=QueryType.DATA_ANALYSIS,
                confidence=0.96,
                reasoning="检测到表格附件且请求包含统计/分析意图",
            )

        if any(keyword in query_text for keyword in ATTACHMENT_ANALYSIS_KEYWORDS) or attachments:
            return RouterDecision(
                query_type=QueryType.ATTACHMENT_ANALYSIS,
                confidence=0.95,
                reasoning="检测到附件请求，优先走附件分析链路",
            )

        return None

    async def classify(
        self,
        query: str,
        context: str = "",
        attachments: list[dict] | None = None,
    ) -> RouterDecision:
        """对查询进行意图分类

        Args:
            query: 用户查询
            context: 对话上下文摘要（可选，用于消歧义）
            attachments: 已解析的附件列表（可选）

        Returns:
            RouterDecision: 路由决策
        """
        attachment_decision = self._classify_with_attachments(query, attachments)
        if attachment_decision:
            return attachment_decision

        user_content = query
        if context:
            user_content = f"[对话上下文摘要]: {context}\n\n[当前消息]: {query}"

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]

        try:
            decision = await self._structured_llm.ainvoke(messages)
            logger.info(
                "路由决策",
                query_type=decision.query_type,
                confidence=decision.confidence,
                reasoning=decision.reasoning,
            )
            return decision
        except Exception as e:
            # 降级：默认路由到知识查询
            logger.warning("路由分类失败，降级为 knowledge_query", error=str(e))
            return RouterDecision(
                query_type=QueryType.KNOWLEDGE_QUERY,
                confidence=0.5,
                reasoning=f"分类失败，降级处理: {str(e)}",
            )

    def classify_sync(self, query: str, context: str = "") -> RouterDecision:
        """同步版本的分类"""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.classify(query, context))
