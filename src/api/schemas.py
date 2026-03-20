"""Pydantic 模型 - API 请求/响应 Schema"""

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# ===== 聊天相关 =====

class AttachmentRef(BaseModel):
    """聊天请求中的附件引用"""
    file_id: str


class PlanStep(BaseModel):
    """plan 模式中的单个步骤"""
    content: str
    status: Literal["pending", "in_progress", "completed"]


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(min_length=1, max_length=10000, description="用户消息")
    thread_id: str | None = Field(default=None, description="会话 ID，为空则创建新会话")
    user_id: str = Field(default="anonymous", description="用户 ID")
    user_role: Literal["门店老板", "销售", "店长", "总部市场", "unknown"] = Field(
        default="unknown", description="用户角色"
    )
    channel: Literal["web", "wecom", "openclaw"] = Field(
        default="web", description="来源渠道"
    )
    mode: Literal["chat", "plan"] = Field(default="chat", description="聊天模式")
    attachments: list[AttachmentRef] = Field(
        default_factory=list, description="关联的已上传附件 ID 列表"
    )

    def get_thread_id(self) -> str:
        """获取或生成 thread_id"""
        return self.thread_id or f"thread_{uuid4().hex[:16]}"


class ChatResponse(BaseModel):
    """聊天响应"""
    thread_id: str
    message_id: str
    content: str
    mode: Literal["chat", "plan"] = "chat"
    plan: list[PlanStep] | None = None
    query_type: str | None = None
    model: str | None = None


class StreamChunk(BaseModel):
    """流式响应 chunk"""
    type: Literal["token", "done", "error", "plan", "step"]
    content: Any = ""
    thread_id: str | None = None
    query_type: str | None = None


# ===== 文件相关 =====

class FileUploadResponse(BaseModel):
    """文件上传响应"""
    file_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    message: str = "文件上传成功"


# ===== 对话历史 =====

class MessageItem(BaseModel):
    """单条消息"""
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None


class ConversationHistory(BaseModel):
    """对话历史"""
    thread_id: str
    title: str | None = None
    channel: str | None = None
    created_at: str | None = None
    last_message_at: str | None = None
    message_count: int | None = None
    messages: list[MessageItem]
    total: int


class ConversationSummary(BaseModel):
    """会话摘要"""
    thread_id: str
    title: str
    channel: str
    created_at: str | None = None
    last_message_at: str | None = None
    message_count: int = 0


class ConversationListResponse(BaseModel):
    """会话列表"""
    items: list[ConversationSummary]
    total: int


class ConversationRenameRequest(BaseModel):
    """会话重命名请求"""
    user_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)


# ===== 用户画像 =====

class UserProfile(BaseModel):
    """用户画像"""
    user_id: str
    role: str = "unknown"
    preferences: dict = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class UserProfileUpdate(BaseModel):
    """用户画像更新请求"""
    role: str | None = None
    preferences: dict | None = None


# ===== Webhook =====

class WecomWebhookPayload(BaseModel):
    """企微 Webhook 数据"""
    msg_type: str
    from_user: str
    content: str | None = None
    media_id: str | None = None
    agent_id: str | None = None


class OpenClawWebhookPayload(BaseModel):
    """OpenClaw Webhook 数据"""
    event_type: str
    user_id: str | None = None
    channel: str | None = None
    message: str | None = None
    metadata: dict = Field(default_factory=dict)


# ===== 健康检查 =====

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: Literal["ok", "degraded", "error"]
    version: str = "0.1.0"
    components: dict = Field(default_factory=dict)
