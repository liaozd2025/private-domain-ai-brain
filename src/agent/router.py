"""查询路由/分类器 - 将用户请求分类为 6 种意图类型

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
    """查询类型枚举 - 6 大类意图"""
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
    sub_intent: Optional[str] = Field(
        default=None,
        description="子意图（可选细分，如内容生成可填 wechat_moment/xiaohongshu/sop 等）",
    )


# 路由系统 Prompt - 内嵌在编排器中使用
ROUTER_SYSTEM_PROMPT = """你是一个查询意图分类器。将用户消息分类为以下 6 类之一：

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

## 复合意图处理
如果消息涉及多个意图，选择**主意图**。例如"分析数据后写个总结报告"主意图是 data_analysis。

## 输出要求
严格按 JSON 格式输出，包含：query_type、confidence（0-1）、reasoning（一句话）、sub_intent（可选，内容生成时可填子类型如 wechat_moment/sop/script）

## Few-shot 示例

输入: {"message": "你好，请问你是谁"}
输出: {"query_type": "chitchat", "confidence": 0.99, "reasoning": "简单问候，无需查库", "sub_intent": null}

输入: {"message": "私域流量和公域流量有什么区别"}
输出: {"query_type": "knowledge_query", "confidence": 0.95, "reasoning": "行业知识问题，需从知识库检索", "sub_intent": null}

输入: {"message": "帮我写一篇小红书推文，主题是夏日限定活动", "context": "用户之前在问朋友圈文案"}
输出: {"query_type": "content_generation", "confidence": 0.97, "reasoning": "明确要求创作平台内容", "sub_intent": "xiaohongshu"}

输入: {"message": "帮我分析这份 CSV 数据", "attachments": [{"file_type": "csv"}]}
输出: {"query_type": "data_analysis", "confidence": 0.98, "reasoning": "表格附件配合分析意图", "sub_intent": null}

输入: {"message": "帮我写个活动方案", "attachments": [{"file_type": "image"}]}
输出: {"query_type": "content_generation", "confidence": 0.92, "reasoning": "主意图为内容创作，附件为参考图片", "sub_intent": "activity_plan"}

输入: {"message": "发消息给张三，告诉他明天活动取消了"}
输出: {"query_type": "tool_action", "confidence": 0.96, "reasoning": "需要执行发送消息的操作", "sub_intent": null}
"""

TABULAR_FILE_TYPES = {"csv", "excel"}
IMAGE_FILE_TYPES = {"image"}
ATTACHMENT_ANALYSIS_KEYWORDS = {
    "图片", "图", "截图", "海报", "照片", "文件", "文档",
    "总结", "摘要", "提取", "识别", "看看", "讲了什么",
}
TABLE_ANALYSIS_KEYWORDS = {
    "分析", "统计", "图表", "趋势", "报表", "对比", "汇总",
    "销售额", "订单", "占比", "分布", "最高", "最低", "均值",
}

# 明显的闲聊关键词（用于启发式短路，避免不必要的 LLM 调用）
CHITCHAT_KEYWORDS = {
    "你好", "hi", "hello", "嗨", "哈喽",
    "谢谢", "感谢", "多谢", "谢了",
    "再见", "拜拜", "bye",
    "哈哈", "哈哈哈", "lol",
    "好的", "好", "嗯", "噢", "哦", "ok", "okay",
    "明白了", "知道了", "明白", "懂了",
    "不客气", "没事", "没关系",
}


class QueryRouter:
    """查询路由器 - 使用 LLM 进行意图分类"""

    def __init__(self, llm):
        self.llm = llm
        self._structured_llm = llm.with_structured_output(RouterDecision)

    def _classify_chitchat_heuristic(self, query: str) -> RouterDecision | None:
        """闲聊启发式短路 - 对明显闲聊词直接返回，不调 LLM"""
        query_stripped = query.strip().lower()
        if query_stripped in CHITCHAT_KEYWORDS:
            return RouterDecision(
                query_type=QueryType.CHITCHAT,
                confidence=0.99,
                reasoning="启发式匹配：明显闲聊词",
            )
        return None

    def _classify_with_attachments(
        self,
        query: str,
        attachments: list[dict] | None = None,
    ) -> RouterDecision | None:
        """附件优先路由规则 - 仅对确定性场景做短路，其余交由 LLM 分类"""
        if not attachments:
            return None

        file_types = {a.get("file_type", "").lower() for a in attachments}
        query_text = query.strip().lower()

        # 表格或图片附件 + 明确分析意图 → 确定性短路到 data_analysis
        has_data_attachment = bool(file_types & (TABULAR_FILE_TYPES | IMAGE_FILE_TYPES))
        has_analysis_intent = any(keyword in query_text for keyword in TABLE_ANALYSIS_KEYWORDS)
        if has_data_attachment and has_analysis_intent:
            return RouterDecision(
                query_type=QueryType.DATA_ANALYSIS,
                confidence=0.96,
                reasoning="检测到数据附件（表格/图片）且请求包含统计/分析意图",
            )

        # 图片/文档附件 + 明确附件分析关键词 → 确定性短路到 attachment_analysis
        # 注意：不再使用 `or attachments` 兜底，避免误路由
        if any(keyword in query_text for keyword in ATTACHMENT_ANALYSIS_KEYWORDS):
            return RouterDecision(
                query_type=QueryType.ATTACHMENT_ANALYSIS,
                confidence=0.95,
                reasoning="检测到附件分析关键词，优先走附件分析链路",
            )

        # 其余有附件的情况交由 LLM 在包含附件信息的上下文下分类
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
        # 1. 闲聊启发式短路（无附件时才短路，有附件时附件可能改变意图）
        if not attachments:
            chitchat_decision = self._classify_chitchat_heuristic(query)
            if chitchat_decision:
                return chitchat_decision

        # 2. 附件确定性短路
        attachment_decision = self._classify_with_attachments(query, attachments)
        if attachment_decision:
            return attachment_decision

        # 3. LLM 分类（包含附件上下文信息）
        parts = []
        if context:
            parts.append(f"[对话上下文]: {context}")
        if attachments:
            file_desc = ", ".join(
                f"{a.get('file_type', 'unknown')}({a.get('filename', '')})"
                for a in attachments
            )
            parts.append(f"[附件]: {file_desc}")
        parts.append(f"[当前消息]: {query}")

        user_content = "\n".join(parts) if len(parts) > 1 else query

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
            # 降级：默认路由到闲聊（避免对闲聊消息触发无意义的 Milvus 搜索）
            logger.warning("路由分类失败，降级为 chitchat", error=str(e))
            return RouterDecision(
                query_type=QueryType.CHITCHAT,
                confidence=0.3,
                reasoning=f"分类失败，降级处理: {str(e)}",
            )
