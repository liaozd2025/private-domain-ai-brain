"""内容生成子智能体 (Content Generation Agent)

职责：
  - 根据用户需求生成各类运营内容
  - 基于角色和渠道调整内容风格
  - 支持多平台适配（朋友圈/抖音/小红书/企微）
"""

from functools import lru_cache

import structlog

from src.agent.runtime import ModernToolAgent
from src.skills.runtime import build_skill_bundle
from src.tools.content_tools import (
    get_brand_guidelines,
    get_platform_rules,
    list_available_templates,
    load_template,
)

logger = structlog.get_logger(__name__)


CONTENT_AGENT_TOOLS = [
    load_template,
    get_platform_rules,
    get_brand_guidelines,
    list_available_templates,
]


BASE_CONTENT_AGENT_SYSTEM_PROMPT = """
你是一个私域运营内容创作专家，专注于帮助私域运营团队生成高质量内容。

## 工作流程

1. **理解需求**：明确内容类型、目标受众、平台渠道
2. **加载资源**：
   - 使用 `load_template` 获取对应内容模板框架
   - 使用 `get_platform_rules` 了解目标平台规则
   - 使用 `get_brand_guidelines` 确保符合品牌调性
3. **创作内容**：基于模板和规则生成内容
4. **输出格式**：
   - 提供完整可直接使用的内容
   - 关键位置标注「{需填写}」供用户替换
   - 如果适合，提供 2-3 个版本供选择

## 角色适配规则

- **门店老板**：突出效果和 ROI，给简洁有力的文案
- **销售**：更多样板话术，注重实战可用性
- **店长**：偏重流程和执行指南，给清单式内容
- **总部市场**：完整方案，有数据支撑，符合品牌规范

## 质量标准

- 内容必须实际可用，不能只给框架
- 关键词和数字要真实合理（不随意编造数据）
- 符合各平台调性（企微≠小红书≠抖音）
- 遵守广告法规，避免绝对化用语
"""


@lru_cache(maxsize=1)
def build_content_generation_system_prompt() -> str:
    """构造内容生成运行时提示词。"""
    skill_bundle = build_skill_bundle(("private-domain-ops", "content-generation"))
    return (
        BASE_CONTENT_AGENT_SYSTEM_PROMPT
        + "\n\n## Runtime Skills\n\n"
        + "下方是当前项目启用的 skill 资料。生成内容时，必须优先遵循这些规则、模板和领域知识。\n\n"
        + skill_bundle
    )


CONTENT_AGENT_SYSTEM_PROMPT = build_content_generation_system_prompt()


class ContentGenerationAgent:
    """内容生成子智能体"""

    def __init__(self, llm):
        self.llm = llm
        self._agent = self._create_agent()

    def _create_agent(self):
        return ModernToolAgent(
            self.llm,
            CONTENT_AGENT_TOOLS,
            CONTENT_AGENT_SYSTEM_PROMPT,
            recursion_limit=10,
            name="content-generation-agent",
        )

    async def generate(
        self,
        query: str,
        user_role: str = "unknown",
        channel: str = "web",
    ) -> str:
        """生成内容

        Args:
            query: 内容生成请求
            user_role: 用户角色
            channel: 目标渠道

        Returns:
            生成的内容
        """
        enriched_query = f"[用户角色: {user_role}] [目标渠道: {channel}]\n\n{query}"

        try:
            result = await self._agent.ainvoke({"input": enriched_query})
            content = result.get("output", "内容生成失败，请重试。")
            logger.info("内容生成完成", user_role=user_role, channel=channel, length=len(content))
            return content
        except Exception as e:
            logger.error("内容生成失败", error=str(e))
            return (
                f"内容生成遇到问题: {str(e)}。请描述得更具体一些，"
                f"例如：「帮我写一篇{channel}平台的活动推广文案，主题是...」"
            )


