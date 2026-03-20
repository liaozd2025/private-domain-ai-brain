"""核心编排器 - Supervisor 模式多智能体编排

架构：
  用户消息 → 路由分类 → 调度子智能体 → 汇总响应

关键设计：
  - Router-First: 路由在编排器内完成，不调用额外 LLM
  - 子智能体作为工具: 每个子智能体封装为可调用工具
  - 上下文隔离: 子智能体有独立上下文，通过结构化接口交互
  - 流式输出: 支持 token-by-token 流式响应
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph

from src.agent.router import QueryRouter, QueryType, RouterDecision
from src.agent.runtime import ModernToolAgent
from src.config import LLMProvider, settings
from src.memory.store import UserProfileStore

logger = structlog.get_logger(__name__)


# ===== 编排器状态 =====

class OrchestratorState(MessagesState):
    """编排器状态 - 扩展 MessagesState"""
    thread_id: str
    user_id: str
    user_role: str                     # 门店老板 / 销售 / 店长 / 总部市场
    channel: str                       # web / wecom / openclaw
    query_type: str | None             # 路由分类结果
    subagent_result: str | None        # 子智能体返回结果
    attachments: list[dict]            # 上传文件信息


# ===== LLM 工厂 =====

def create_llm(provider: LLMProvider = None, model: str = None, streaming: bool = True):
    """创建 LLM 实例"""
    provider = provider or settings.primary_llm
    if isinstance(provider, str):
        provider = LLMProvider(provider)
    model = model or settings.primary_model

    if provider == LLMProvider.CLAUDE:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            streaming=streaming,
            max_tokens=4096,
        )
    elif provider == LLMProvider.QWEN:
        from langchain_community.chat_models import ChatTongyi
        return ChatTongyi(
            model=model,
            dashscope_api_key=settings.dashscope_api_key,
            streaming=streaming,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            streaming=streaming,
        )


# ===== 角色感知系统 Prompt =====

ROLE_CONTEXTS = {
    "门店老板": """你正在服务的是一位门店老板。
- 关注重点：营收增长、成本控制、团队管理、客户留存
- 语言风格：直接、务实，给出可落地的行动建议
- 内容详略：突出结果和 ROI，减少方法论说教
- 常见需求：活动策划、客户裂变、节日营销、店面运营""",

    "销售": """你正在服务的是一位销售人员。
- 关注重点：客户跟进、成交技巧、话术优化、业绩达成
- 语言风格：有激情、给力量，提供具体话术和方法
- 内容详略：多给样板话术，少讲理论
- 常见需求：客户沟通模板、异议处理、活动推广文案""",

    "店长": """你正在服务的是一位店长。
- 关注重点：门店管理、团队协作、执行落地、日常运营
- 语言风格：清晰、有条理，重视执行步骤
- 内容详略：多给 SOP 和检查清单，注重可执行性
- 常见需求：排班管理、库存盘点、员工培训、周报模板""",

    "总部市场": """你正在服务的是总部市场人员。
- 关注重点：品牌一致性、规模化运营、数据分析、策略制定
- 语言风格：专业、系统，注重数据支撑
- 内容详略：提供完整方案和数据分析，注重战略视角
- 常见需求：市场活动方案、品牌内容、数据报告、渠道策略""",

    "unknown": """你正在服务一位私域运营从业者。
- 提供专业、实用的私域运营建议
- 语言风格：友好、清晰
- 如有需要，可以询问对方的具体角色以提供更精准的建议""",
}


def build_system_prompt(user_role: str, user_profile: dict = None) -> str:
    """构建角色感知的系统 Prompt"""
    role_context = ROLE_CONTEXTS.get(user_role, ROLE_CONTEXTS["unknown"])

    profile_context = ""
    if user_profile:
        topics = user_profile.get("topics", [])
        if topics:
            profile_context = f"\n\n**用户历史关注话题**: {', '.join(topics[-5:])}"

    return f"""你是「私域运营专家 AI 智脑」，一个专注于私域运营领域的专业 AI 助手。

## 你的角色认知
{role_context}{profile_context}

## 行为准则
1. **智能判断**：区分闲聊和专业问题，闲聊时自然对话，专业问题给出深度解答
2. **拒绝幻觉**：不确定时明确说"我没有相关信息"，而非编造答案
3. **带引用**：引用知识库时标注来源，提升可信度
4. **简洁有力**：避免废话，每个回答都有实际价值
5. **中文优先**：始终用简体中文回答

## 专业领域
私域流量运营 | 社群管理 | 会员体系 | 内容营销 | 裂变增长 | 数据分析 | 企微运营
"""


# ===== 编排器节点 =====

class Orchestrator:
    """核心编排器"""

    def __init__(self, checkpointer=None):
        # 主力 LLM
        self.llm = create_llm(streaming=True)
        self.vision_llm = create_llm(
            provider=settings.vision_llm,
            model=settings.vision_model,
            streaming=False,
        )

        # 路由 LLM (轻量)
        router_llm = create_llm(
            provider=settings.router_llm,
            model=settings.router_model,
            streaming=False,
        )
        self.router = QueryRouter(router_llm)

        # 用户画像 Store
        self.profile_store = UserProfileStore()

        # Checkpointer (会话持久化)
        self.checkpointer = checkpointer

        # 构建 LangGraph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建编排器状态图"""
        builder = StateGraph(OrchestratorState)

        # 节点
        builder.add_node("route", self._route_node)
        builder.add_node("chitchat", self._chitchat_node)
        builder.add_node("knowledge_query", self._knowledge_query_node)
        builder.add_node("data_analysis", self._data_analysis_node)
        builder.add_node("attachment_analysis", self._attachment_analysis_node)
        builder.add_node("content_generation", self._content_generation_node)
        builder.add_node("tool_action", self._tool_action_node)
        builder.add_node("finalize", self._finalize_node)

        # 边
        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            self._routing_condition,
            {
                QueryType.CHITCHAT: "chitchat",
                QueryType.KNOWLEDGE_QUERY: "knowledge_query",
                QueryType.DATA_ANALYSIS: "data_analysis",
                QueryType.ATTACHMENT_ANALYSIS: "attachment_analysis",
                QueryType.CONTENT_GENERATION: "content_generation",
                QueryType.TOOL_ACTION: "tool_action",
            },
        )
        for node in [
            "chitchat",
            "knowledge_query",
            "data_analysis",
            "attachment_analysis",
            "content_generation",
            "tool_action",
        ]:
            builder.add_edge(node, "finalize")
        builder.add_edge("finalize", END)

        return builder.compile(checkpointer=self.checkpointer)

    async def _route_node(self, state: OrchestratorState) -> dict:
        """路由节点 - 分类用户意图"""
        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        # 获取对话上下文摘要（最近 3 轮）
        recent_messages = state["messages"][-6:-1]  # 排除最新消息
        context = " | ".join([
            f"{'用户' if isinstance(m, HumanMessage) else 'AI'}: {str(m.content)[:50]}"
            for m in recent_messages
        ])

        decision: RouterDecision = await self.router.classify(
            query,
            context,
            attachments=state.get("attachments", []),
        )

        return {"query_type": decision.query_type.value}

    def _routing_condition(self, state: OrchestratorState) -> str:
        """路由条件边"""
        return state.get("query_type", QueryType.CHITCHAT)

    async def _chitchat_node(self, state: OrchestratorState) -> dict:
        """闲聊节点 - 直接 LLM 回答，不查知识库"""
        user_profile = await self.profile_store.get_profile(state.get("user_id", ""))
        system_prompt = build_system_prompt(state.get("user_role", "unknown"), user_profile)

        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm.ainvoke(messages)

        return {
            "messages": [response],
            "subagent_result": response.content,
        }

    async def _knowledge_query_node(self, state: OrchestratorState) -> dict:
        """知识查询节点 - 调用 KB 子智能体"""
        from src.subagents.knowledge_base import KBAgent

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        user_profile = await self.profile_store.get_profile(state.get("user_id", ""))
        system_prompt = build_system_prompt(state.get("user_role", "unknown"), user_profile)

        kb_agent = KBAgent(llm=self.llm)
        result = await kb_agent.query(
            query=query,
            user_role=state.get("user_role", "unknown"),
            system_prompt=system_prompt,
        )

        return {
            "messages": [AIMessage(content=result)],
            "subagent_result": result,
        }

    async def _data_analysis_node(self, state: OrchestratorState) -> dict:
        """数据分析节点 - 调用 Data Analysis 子智能体"""
        from src.subagents.data_analysis import DataAnalysisAgent

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        da_agent = DataAnalysisAgent(llm=self.llm)
        result = await da_agent.analyze(
            query=query,
            attachments=state.get("attachments", []),
            user_role=state.get("user_role", "unknown"),
        )

        return {
            "messages": [AIMessage(content=result)],
            "subagent_result": result,
        }

    async def _attachment_analysis_node(self, state: OrchestratorState) -> dict:
        """附件分析节点 - 图片/文档/混合附件理解"""
        from src.subagents.attachment_analysis import AttachmentAnalysisAgent

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        attachment_agent = AttachmentAnalysisAgent(
            text_llm=self.llm,
            vision_llm=self.vision_llm,
        )
        result = await attachment_agent.analyze(
            query=query,
            attachments=state.get("attachments", []),
            user_role=state.get("user_role", "unknown"),
        )

        return {
            "messages": [AIMessage(content=result)],
            "subagent_result": result,
        }

    async def _content_generation_node(self, state: OrchestratorState) -> dict:
        """内容生成节点 - 调用 Content Generation 子智能体"""
        from src.subagents.content_generation import ContentGenerationAgent

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        cg_agent = ContentGenerationAgent(llm=self.llm)
        result = await cg_agent.generate(
            query=query,
            user_role=state.get("user_role", "unknown"),
            channel=state.get("channel", "web"),
        )

        return {
            "messages": [AIMessage(content=result)],
            "subagent_result": result,
        }

    async def _tool_action_node(self, state: OrchestratorState) -> dict:
        """工具操作节点 - 调用 OpenClaw 等工具"""
        from src.tools.openclaw_tools import OpenClawToolkit

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)

        # 使用 LLM + 工具 ReAct 循环执行操作
        toolkit = OpenClawToolkit()
        tools = toolkit.get_tools()
        executor = ModernToolAgent(
            self.llm,
            tools,
            "你是一个工具操作助手，根据用户指令调用适当的工具完成操作。",
            recursion_limit=10,
            name="tool-action-agent",
        )

        try:
            result = await executor.ainvoke({"input": query})
            response = result.get("output", "操作已完成")
        except Exception as e:
            logger.error("工具操作失败", error=str(e))
            response = f"操作执行失败: {str(e)}"

        return {
            "messages": [AIMessage(content=response)],
            "subagent_result": response,
        }

    async def _finalize_node(self, state: OrchestratorState) -> dict:
        """后处理节点 - 更新用户画像"""
        from src.memory.profile_middleware import extract_and_update_profile

        user_id = state.get("user_id", "")
        if user_id:
            # 异步提取画像（不阻塞响应）
            import asyncio
            asyncio.create_task(
                extract_and_update_profile(
                    user_id=user_id,
                    messages=state["messages"],
                    llm=self.llm,
                )
            )

        return {}

    async def invoke(
        self,
        message: str,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        channel: str = "web",
        attachments: list[dict] = None,
    ) -> str:
        """调用编排器处理单条消息"""
        config = RunnableConfig(
            configurable={"thread_id": thread_id},
        )

        initial_state = {
            "messages": [HumanMessage(content=message)],
            "thread_id": thread_id,
            "user_id": user_id,
            "user_role": user_role,
            "channel": channel,
            "query_type": None,
            "subagent_result": None,
            "attachments": attachments or [],
        }

        result = await self.graph.ainvoke(initial_state, config=config)
        last_message = result["messages"][-1]
        return last_message.content if hasattr(last_message, "content") else str(last_message)

    async def stream(
        self,
        message: str,
        thread_id: str,
        user_id: str,
        user_role: str = "unknown",
        channel: str = "web",
        attachments: list[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """流式调用编排器"""
        config = RunnableConfig(
            configurable={"thread_id": thread_id},
        )

        initial_state = {
            "messages": [HumanMessage(content=message)],
            "thread_id": thread_id,
            "user_id": user_id,
            "user_role": user_role,
            "channel": channel,
            "query_type": None,
            "subagent_result": None,
            "attachments": attachments or [],
        }

        async for event in self.graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            kind = event["event"]
            # 只输出 LLM token 流
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield chunk.content


# ===== 全局编排器实例 =====

_orchestrator: Orchestrator | None = None


async def get_orchestrator() -> Orchestrator:
    """获取全局编排器实例（单例）"""
    global _orchestrator
    if _orchestrator is None:
        from src.memory.checkpointer import get_checkpointer
        checkpointer = await get_checkpointer()
        _orchestrator = Orchestrator(checkpointer=checkpointer)
        logger.info("编排器初始化完成")
    return _orchestrator
