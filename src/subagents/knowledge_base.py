"""知识库子智能体 (KB Agent)

职责：
  - 接收知识查询请求
  - 智能 RAG 流程：查询分解 → 多次检索 → 重排序 → 带引用答案合成
  - 低置信度时明确说"没有相关信息"而非幻觉
"""

from functools import lru_cache

import structlog

from src.agent.runtime import ModernToolAgent
from src.skills.runtime import build_skill_bundle
from src.tools.milvus_tools import search_and_rerank, search_knowledge_base

logger = structlog.get_logger(__name__)


# 子智能体可使用的工具集
KB_TOOLS = [search_knowledge_base, search_and_rerank]


BASE_KB_AGENT_SYSTEM_PROMPT = """你是一个专注于私域运营领域的知识检索专家。

## 工作流程
1. **分析查询**：理解用户问题的核心意图，判断是否需要多角度检索
2. **智能检索**：使用 `search_and_rerank` 工具检索最相关内容（优先使用高精度模式）
   - 复杂问题可拆分为多个子问题分别检索
   - 如有文档类型线索，使用 `doc_type` 参数过滤
3. **评估结果**：
   - 检索结果相关性高（重排分数 > 0.5）→ 基于结果合成答案
   - 检索结果相关性低或为空 → 明确告知"知识库暂无此方面内容"
4. **合成答案**：
   - 基于检索内容回答，保持事实准确
   - 在答案末尾添加【参考来源】章节，列出引用文档
   - 根据用户角色调整语言和详略

## 重要规则
- **绝对不要凭空编造**：检索为空时，直接说"暂无相关资料"
- **引用要准确**：只引用检索到的真实内容
- **简洁优先**：答案要有实际价值，避免堆砌检索内容
"""


@lru_cache(maxsize=1)
def build_kb_system_prompt() -> str:
    """构造知识库运行时提示词。"""
    skill_bundle = build_skill_bundle(("private-domain-ops", "knowledge-base"))
    return (
        BASE_KB_AGENT_SYSTEM_PROMPT
        + "\n\n## Runtime Skills\n\n"
        + (
            "下方是当前项目启用的 skill 资料。检索、过滤和回答时，"
            "必须遵循这些检索规则与领域知识。\n\n"
        )
        + skill_bundle
    )


KB_AGENT_SYSTEM_PROMPT = build_kb_system_prompt()


class KBAgent:
    """知识库子智能体"""

    def __init__(self, llm):
        self.llm = llm
        self._agent = self._create_agent()

    def _create_agent(self):
        """创建 ReAct 工具调用 Agent"""
        return ModernToolAgent(
            self.llm,
            KB_TOOLS,
            KB_AGENT_SYSTEM_PROMPT,
            recursion_limit=8,
            name="kb-agent",
        )

    async def query(
        self,
        query: str,
        user_role: str = "unknown",
        system_prompt: str = "",
    ) -> str:
        """执行知识查询

        Args:
            query: 用户查询
            user_role: 用户角色（影响答案风格）
            system_prompt: 额外的系统上下文（可选）

        Returns:
            带引用的知识库答案
        """
        # 将角色信息注入查询上下文
        enriched_query = query
        if user_role and user_role != "unknown":
            enriched_query = f"[用户角色: {user_role}]\n\n{query}"

        try:
            result = await self._agent.ainvoke({"input": enriched_query})
            answer = result.get("output", "抱歉，暂时无法处理您的查询。")
            logger.info("KB Agent 查询完成", query=query[:50], answer_length=len(answer))
            return answer
        except Exception as e:
            logger.error("KB Agent 查询失败", error=str(e))
            return f"知识查询失败: {str(e)}。请稍后重试或换个方式描述您的问题。"


