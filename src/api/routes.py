"""API 路由 - 核心端点。

端点列表：
  POST /chat - 发送消息（同步）
  POST /files/upload - 文件上传
  GET /conversations/{id} - 对话历史
  GET /users/{id}/profile - 用户画像
  GET /health - 健康检查
"""

import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    ConversationListResponse,
    ConversationRenameRequest,
    ConversationSummary,
    FileUploadResponse,
    HealthResponse,
    MessageItem,
    UserProfile,
    UserProfileUpdate,
)
from src.config import settings
from src.memory.attachments import (
    AttachmentAccessError,
    AttachmentNotFoundError,
    resolve_attachment_refs,
    save_attachment_metadata,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ===== 依赖注入 =====

async def get_orchestrator_dep():
    """获取编排器依赖"""
    from src.agent.orchestrator import get_orchestrator
    return await get_orchestrator()


async def get_plan_runner_dep():
    """获取 plan 模式执行器依赖"""
    from src.agent.plan_runner import get_plan_runner
    return await get_plan_runner()


# ===== 聊天端点 =====

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator=Depends(get_orchestrator_dep),
    plan_runner=Depends(get_plan_runner_dep),
):
    """发送消息，获取 AI 回答（同步模式）

    对于流式响应，请使用 WebSocket 端点 /chat/stream
    """
    thread_id = request.get_thread_id()

    logger.info(
        "收到聊天请求",
        thread_id=thread_id,
        user_id=request.user_id,
        user_role=request.user_role,
        message_preview=request.message[:50],
    )

    try:
        resolved_attachments = resolve_attachment_refs(
            [a.model_dump() for a in request.attachments],
            request.user_id,
        )

        if request.mode == "plan":
            response = await plan_runner.invoke(
                message=request.message,
                thread_id=thread_id,
                user_id=request.user_id,
                user_role=request.user_role,
                channel=request.channel,
                attachments=resolved_attachments,
            )
            from src.memory.conversations import record_conversation_turn

            await record_conversation_turn(
                thread_id=thread_id,
                user_id=request.user_id,
                message=request.message,
                channel=request.channel,
            )
            return ChatResponse(
                thread_id=thread_id,
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                content=response.content,
                mode="plan",
                plan=response.plan,
                model=response.model,
            )

        response = await orchestrator.invoke(
            message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_role,
            channel=request.channel,
            attachments=resolved_attachments,
        )

        from src.memory.conversations import record_conversation_turn

        await record_conversation_turn(
            thread_id=thread_id,
            user_id=request.user_id,
            message=request.message,
            channel=request.channel,
        )

        return ChatResponse(
            thread_id=thread_id,
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            content=response,
            mode="chat",
        )

    except AttachmentAccessError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AttachmentNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("聊天请求失败", error=str(e), thread_id=thread_id)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


# ===== 文件上传 =====

@router.post("/files/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form(default="anonymous"),
    thread_id: str | None = Form(default=None),
):
    """上传文件（Excel/CSV/PDF/Word/图片）

    返回 file_id，后续在 chat 请求中通过 attachments 引用
    """
    # 校验文件类型
    allowed_types = {
        ".xlsx": "excel",
        ".xls": "excel",
        ".csv": "csv",
        ".pdf": "pdf",
        ".docx": "word",
        ".doc": "word",
        ".txt": "text",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webp": "image",
    }

    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {suffix}，支持：{', '.join(allowed_types.keys())}",
        )

    # 校验文件大小
    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大支持 {settings.max_upload_size_mb}MB",
        )

    # 保存文件
    file_id = uuid.uuid4().hex
    upload_path = Path(settings.upload_dir) / user_id
    upload_path.mkdir(parents=True, exist_ok=True)

    safe_filename = f"{file_id}{suffix}"
    file_path = upload_path / safe_filename

    with open(file_path, "wb") as f:
        f.write(content)

    save_attachment_metadata(
        file_id=file_id,
        user_id=user_id,
        filename=file.filename,
        file_type=allowed_types[suffix],
        file_path=str(file_path),
        thread_id=thread_id,
    )

    logger.info(
        "文件上传成功",
        file_id=file_id,
        filename=file.filename,
        size_bytes=len(content),
        user_id=user_id,
    )

    return FileUploadResponse(
        file_id=file_id,
        filename=file.filename,
        file_type=allowed_types[suffix],
        file_size_bytes=len(content),
    )


# ===== 对话历史 =====


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
):
    """获取用户会话列表。"""
    from src.memory.conversations import get_conversation_store

    store = get_conversation_store()
    result = await store.list_by_user(user_id=user_id, limit=limit, offset=offset)
    return ConversationListResponse(
        items=[ConversationSummary(**item) for item in result["items"]],
        total=result["total"],
    )


@router.get("/conversations/{thread_id}", response_model=ConversationHistory)
async def get_conversation(
    thread_id: str,
    limit: int = 50,
    user_id: str | None = None,
):
    """获取对话历史"""
    try:
        from src.memory.checkpointer import get_checkpointer
        from src.memory.conversations import get_conversation_store

        store = get_conversation_store()
        metadata = await store.get_by_thread(
            thread_id,
            user_id=user_id,
            include_deleted=True,
        )
        if user_id and metadata is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        if metadata and metadata["is_deleted"]:
            raise HTTPException(status_code=404, detail="对话不存在")

        checkpointer = await get_checkpointer()

        config = {"configurable": {"thread_id": thread_id}}
        checkpoint = await checkpointer.aget(config)

        if not checkpoint:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = checkpoint.get("channel_values", {}).get("messages", [])

        message_items = []
        for msg in messages[-limit:]:
            from langchain_core.messages import AIMessage, HumanMessage
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            else:
                continue
            message_items.append(MessageItem(role=role, content=str(msg.content)))

        return ConversationHistory(
            thread_id=thread_id,
            title=metadata["title"] if metadata else None,
            channel=metadata["channel"] if metadata else None,
            created_at=metadata["created_at"] if metadata else None,
            last_message_at=metadata["last_message_at"] if metadata else None,
            message_count=metadata["message_count"] if metadata else len(message_items),
            messages=message_items,
            total=len(message_items),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取对话历史失败", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/conversations/{thread_id}", response_model=ConversationSummary)
async def rename_conversation(thread_id: str, request: ConversationRenameRequest):
    """重命名会话。"""
    from src.memory.conversations import get_conversation_store

    store = get_conversation_store()
    conversation = await store.rename(
        thread_id=thread_id,
        user_id=request.user_id,
        title=request.title,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    return ConversationSummary(**conversation)


@router.delete("/conversations/{thread_id}", status_code=204)
async def delete_conversation(thread_id: str, user_id: str):
    """软删除会话。"""
    from src.memory.conversations import get_conversation_store

    store = get_conversation_store()
    deleted = await store.soft_delete(thread_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在")
    return Response(status_code=204)


# ===== 用户画像 =====

@router.get("/users/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(user_id: str):
    """获取用户画像"""
    from src.memory.store import get_profile_store
    store = get_profile_store()
    profile = await store.get_profile(user_id)

    return UserProfile(
        user_id=user_id,
        role=profile.get("role", "unknown"),
        preferences=profile.get("preferences", {}),
        topics=profile.get("topics", []),
    )


@router.patch("/users/{user_id}/profile", response_model=UserProfile)
async def update_user_profile(user_id: str, updates: UserProfileUpdate):
    """手动更新用户画像"""
    from src.memory.store import get_profile_store
    store = get_profile_store()

    update_data = updates.model_dump(exclude_none=True)
    await store.update_profile(user_id, update_data)

    profile = await store.get_profile(user_id)
    return UserProfile(user_id=user_id, **profile)


# ===== 健康检查 =====

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """服务健康检查"""
    components = {}

    # 检查数据库
    try:
        from src.memory.checkpointer import get_checkpointer
        await get_checkpointer()
        components["database"] = "ok"
    except Exception as e:
        components["database"] = f"error: {str(e)}"

    # 检查 Milvus（懒加载，不强制连接）
    components["milvus"] = "not_checked"

    overall = (
        "ok"
        if all(v == "ok" or v == "not_checked" for v in components.values())
        else "degraded"
    )

    return HealthResponse(status=overall, components=components)
