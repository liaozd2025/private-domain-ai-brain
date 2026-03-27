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
    HandoffClaimRequest,
    HandoffDetail,
    HandoffListResponse,
    HandoffReplyRequest,
    HandoffResolveRequest,
    HandoffSummary,
    HealthResponse,
    MessageItem,
    PagingInfo,
    UserProfile,
    UserProfileUpdate,
)
from src.config import settings
from src.memory.attachments import (
    AttachmentAccessError,
    AttachmentNotFoundError,
    resolve_attachment_refs_from_db,
    save_attachment_metadata,
)
from src.memory.db import ensure_managed_schema, get_async_engine, uploaded_files_table

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


async def get_mode_selector_dep():
    """获取自动模式选择器依赖"""
    from src.agent.mode_selector import get_mode_selector
    return await get_mode_selector()


async def get_customer_service_supervisor_dep():
    """获取客服编排器依赖。"""
    from src.agent.customer_service import get_customer_service_supervisor
    return await get_customer_service_supervisor()


async def get_customer_service_store_dep():
    """获取客服存储依赖。"""
    from src.memory.customer_service import get_customer_service_store
    return get_customer_service_store()


def _is_customer_role(user_role: str) -> bool:
    return user_role == "customer"


def _customer_sender_to_role(sender_type: str) -> str:
    mapping = {
        "customer": "user",
        "ai": "assistant",
        "human": "human",
        "system": "system",
    }
    return mapping.get(sender_type, "assistant")


async def _check_database_health() -> str:
    """检查数据库连接状态，不向调用方暴露底层异常。"""
    try:
        from src.memory.checkpointer import get_checkpointer

        await get_checkpointer()
        return "ok"
    except Exception as e:
        logger.warning("数据库健康检查失败", error=str(e))
        return "error"


async def _check_milvus_health() -> str:
    """检查 Milvus 连接状态，不向调用方暴露底层异常。"""
    alias = "healthcheck"
    try:
        from pymilvus import connections, utility

        connections.connect(alias=alias, **settings.milvus_connection_args)
        utility.has_collection(settings.milvus_collection_name, using=alias)
        return "ok"
    except Exception as e:
        logger.warning("Milvus 健康检查失败", error=str(e))
        return "error"
    finally:
        try:
            from pymilvus import connections

            connections.disconnect(alias)
        except Exception:
            pass


# ===== 聊天端点 =====

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator=Depends(get_orchestrator_dep),
    plan_runner=Depends(get_plan_runner_dep),
    mode_selector=Depends(get_mode_selector_dep),
    customer_service_supervisor=Depends(get_customer_service_supervisor_dep),
):
    """发送消息，获取 AI 回答（同步模式）

    对于流式响应，请使用 SSE 端点 POST /chat/stream
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
        resolved_attachments = await resolve_attachment_refs_from_db(
            [a.model_dump() for a in request.attachments],
            request.user_id,
        )

        if _is_customer_role(request.user_role):
            from src.memory.conversations import get_conversation_store

            store = get_conversation_store()
            await store.save_user_message(
                thread_id=thread_id,
                user_id=request.user_id,
                user_role=request.user_role,
                message=request.message,
                channel=request.channel,
                store_id=request.store_id,
            )
            result = await customer_service_supervisor.invoke(
                message=request.message,
                thread_id=thread_id,
                user_id=request.user_id,
                channel=request.channel,
                store_id=request.store_id,
            )
            try:
                await store.save_assistant_message(
                    thread_id=thread_id,
                    user_id=request.user_id,
                    channel=request.channel,
                    store_id=request.store_id,
                    content=result.content,
                )
            except Exception as _exc:
                logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))
            return ChatResponse(
                thread_id=thread_id,
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                content=result.content,
                mode="chat",
                requested_mode=request.mode,
                resolved_mode="chat",
            )

        from src.memory.conversations import get_conversation_store

        store = get_conversation_store()
        await store.save_user_message(
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_role,
            message=request.message,
            channel=request.channel,
            store_id=request.store_id,
        )

        mode_decision = await mode_selector.resolve_mode(
            message=request.message,
            requested_mode=request.mode,
            attachments=resolved_attachments,
            user_role=request.user_role,
            channel=request.channel,
        )
        resolved_mode = str(mode_decision["resolved_mode"])

        if resolved_mode == "plan":
            response = await plan_runner.invoke(
                message=request.message,
                thread_id=thread_id,
                user_id=request.user_id,
                user_role=request.user_role,
                channel=request.channel,
                store_id=request.store_id,
                attachments=resolved_attachments,
            )
            try:
                await store.save_assistant_message(
                    thread_id=thread_id,
                    user_id=request.user_id,
                    channel=request.channel,
                    store_id=request.store_id,
                    content=response.content,
                )
            except Exception as _exc:
                logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))
            return ChatResponse(
                thread_id=thread_id,
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                content=response.content,
                mode="plan",
                requested_mode=request.mode,
                resolved_mode="plan",
                plan=response.plan,
                model=response.model,
            )

        response = await orchestrator.invoke(
            message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_role,
            channel=request.channel,
            store_id=request.store_id,
            attachments=resolved_attachments,
        )
        try:
            await store.save_assistant_message(
                thread_id=thread_id,
                user_id=request.user_id,
                channel=request.channel,
                store_id=request.store_id,
                content=response,
            )
        except Exception as _exc:
            logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))

        return ChatResponse(
            thread_id=thread_id,
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            content=response,
            mode="chat",
            requested_mode=request.mode,
            resolved_mode="chat",
        )

    except AttachmentAccessError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AttachmentNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("聊天请求失败", error=str(e), thread_id=thread_id)
        raise HTTPException(status_code=500, detail="请求处理失败，请稍后重试")


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

    await ensure_managed_schema()
    async with get_async_engine().begin() as conn:
        await conn.execute(
            uploaded_files_table.insert().values(
                file_id=file_id,
                thread_id=thread_id,
                user_id=user_id,
                filename=file.filename,
                file_path=str(file_path),
                file_type=allowed_types[suffix],
                file_size_bytes=len(content),
            )
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
    before: str | None = None,
    after: str | None = None,
):
    """获取用户会话列表。"""
    from src.memory.conversations import get_conversation_store

    store = get_conversation_store()
    try:
        result = await store.list_by_user(
            user_id=user_id,
            limit=limit,
            before=before,
            after=after,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ConversationListResponse(
        items=[ConversationSummary(**item) for item in result["items"]],
        total=result["total"],
        paging=PagingInfo(**result.get("paging", {})),
    )


@router.get("/conversations/{thread_id}", response_model=ConversationHistory)
async def get_conversation(
    thread_id: str,
    limit: int = 50,
    user_id: str | None = None,
    before: str | None = None,
    after: str | None = None,
):
    """获取对话历史"""
    try:
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
        if metadata is None or metadata.get("message_source") != "unified":
            raise HTTPException(status_code=404, detail="对话不存在")

        message_result = await store.list_messages(
            thread_id=thread_id,
            user_id=user_id,
            limit=limit,
            before=before,
            after=after,
        )
        message_items = [
            MessageItem(
                id=item["id"],
                role=item["role"],
                content=item["content"],
                created_at=item.get("created_at"),
            )
            for item in message_result["items"]
        ]

        return ConversationHistory(
            thread_id=thread_id,
            title=metadata["title"],
            channel=metadata["channel"],
            created_at=metadata["created_at"],
            last_message_at=metadata["last_message_at"],
            message_count=metadata["message_count"],
            messages=message_items,
            total=message_result["total"],
            paging=PagingInfo(**message_result.get("paging", {})),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取对话历史失败", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail="获取对话历史失败，请稍后重试")


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


@router.get("/handoffs", response_model=HandoffListResponse)
async def list_handoffs(
    status: str | None = None,
    channel: str | None = None,
    limit: int = 20,
    offset: int = 0,
    customer_service_store=Depends(get_customer_service_store_dep),
):
    """获取人工接管队列。"""
    result = await customer_service_store.list_handoffs(
        status=status,
        channel=channel,
        limit=limit,
        offset=offset,
    )
    return HandoffListResponse(
        items=[HandoffSummary(**item) for item in result["items"]],
        total=result["total"],
    )


@router.get("/handoffs/{handoff_id}", response_model=HandoffDetail)
async def get_handoff_detail(
    handoff_id: str,
    customer_service_store=Depends(get_customer_service_store_dep),
):
    """获取人工接管详情。"""
    detail = await customer_service_store.get_handoff_detail(handoff_id)
    if not detail:
        raise HTTPException(status_code=404, detail="接管记录不存在")
    return HandoffDetail(**detail)


@router.post("/handoffs/{handoff_id}/claim", response_model=HandoffSummary)
async def claim_handoff(
    handoff_id: str,
    request: HandoffClaimRequest,
    customer_service_store=Depends(get_customer_service_store_dep),
):
    """人工领取会话。"""
    handoff = await customer_service_store.claim_handoff(
        handoff_id=handoff_id,
        agent_id=request.agent_id,
    )
    if not handoff:
        raise HTTPException(status_code=404, detail="接管记录不存在")
    return HandoffSummary(**handoff)


@router.post("/handoffs/{handoff_id}/reply", response_model=HandoffSummary)
async def reply_handoff(
    handoff_id: str,
    request: HandoffReplyRequest,
    customer_service_store=Depends(get_customer_service_store_dep),
):
    """人工回复客户。"""
    handoff = await customer_service_store.reply_to_handoff(
        handoff_id=handoff_id,
        agent_id=request.agent_id,
        content=request.content,
        resolve_after_reply=request.resolve_after_reply,
    )
    if not handoff:
        raise HTTPException(status_code=404, detail="接管记录不存在")

    if handoff["channel"] == "wecom":
        from src.api.webhooks import send_wecom_message

        await send_wecom_message(to_user=handoff["user_id"], content=request.content)
    elif handoff["channel"] == "openclaw":
        from src.api.webhooks import send_openclaw_message

        await send_openclaw_message(
            user_id=handoff["user_id"],
            channel=handoff["channel"],
            content=request.content,
        )

    return HandoffSummary(**handoff)


@router.post("/handoffs/{handoff_id}/resolve", response_model=HandoffSummary)
async def resolve_handoff(
    handoff_id: str,
    request: HandoffResolveRequest,
    customer_service_store=Depends(get_customer_service_store_dep),
):
    """结束人工接管。"""
    handoff = await customer_service_store.resolve_handoff(
        handoff_id=handoff_id,
        agent_id=request.agent_id,
        resolution_note=request.resolution_note,
    )
    if not handoff:
        raise HTTPException(status_code=404, detail="接管记录不存在")
    return HandoffSummary(**handoff)


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
    components = {
        "database": await _check_database_health(),
        "milvus": await _check_milvus_health(),
    }

    overall = (
        "ok"
        if all(v == "ok" for v in components.values())
        else "degraded"
    )

    return HealthResponse(status=overall, components=components)
