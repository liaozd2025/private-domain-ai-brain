"""用户画像自动提取中间件

在每次对话结束后，从对话中自动提取用户信息并更新画像。
设计为异步非阻塞，不影响主响应速度。
"""

import structlog
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger(__name__)


class ProfileExtractionResult(BaseModel):
    """画像提取结果"""
    role: str | None = Field(default=None, description="用户角色")
    topics: list[str] = Field(default_factory=list, description="关注的话题")
    preferences: dict = Field(default_factory=dict, description="偏好设置")

    @field_validator("preferences", mode="before")
    @classmethod
    def normalize_preferences(cls, value):
        """容忍模型返回空字符串等非对象空值。"""
        if value in (None, "", []):
            return {}
        if isinstance(value, dict):
            return value
        return {}


EXTRACTION_PROMPT = """分析以下对话，提取用户信息。

**对话内容**：
{conversation}

**任务**：
从对话中提取：
1. `role`：用户角色（门店老板/销售/店长/总部市场，如无法判断留空）
2. `topics`：本次对话涉及的主要话题关键词（最多 3 个，如"社群运营"、"裂变活动"）
3. `preferences`：用户的特殊偏好（如语言风格、关注点等，可为空）

只提取确定的信息，不要猜测。以 JSON 格式输出。
"""


async def extract_and_update_profile(
    user_id: str,
    messages: list[BaseMessage],
    llm,
) -> None:
    """从对话中提取用户画像信息并更新

    Args:
        user_id: 用户 ID
        messages: 对话消息列表
        llm: LLM 实例（用于提取）
    """
    if not user_id or not messages:
        return

    try:
        from src.memory.store import get_profile_store

        # 只处理最近几轮对话
        recent_messages = messages[-6:]
        conversation = "\n".join([
            f"{'用户' if isinstance(m, HumanMessage) else 'AI'}: {str(m.content)[:200]}"
            for m in recent_messages
        ])

        # 调用 LLM 提取（json_mode 避免 OpenAI function-calling 路径产生 parsed 字段序列化警告）
        extraction_llm = llm.with_structured_output(ProfileExtractionResult, method="json_mode")
        from langchain_core.messages import HumanMessage as HM
        result = await extraction_llm.ainvoke([
            HM(content=EXTRACTION_PROMPT.format(conversation=conversation))
        ])

        # 构建更新字典
        updates = {}
        if result.role:
            updates["role"] = result.role
        if result.topics:
            updates["topics"] = result.topics
        if result.preferences:
            updates["preferences"] = result.preferences

        if updates:
            store = get_profile_store()
            await store.update_profile(user_id, updates)
            logger.debug("用户画像自动更新", user_id=user_id, updates=updates)

    except Exception as e:
        # 画像更新失败不影响主流程
        logger.warning("画像自动提取失败", user_id=user_id, error=str(e))
