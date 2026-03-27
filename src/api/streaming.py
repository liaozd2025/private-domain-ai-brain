"""SSE 流式端点

支持 token-by-token 实时流式响应，适合前端聊天界面。

协议：
  Client → Server: POST /api/v1/chat/stream
    Content-Type: application/json
    {"message": "...", "thread_id": "...", "user_id": "...", "user_role": "...", "store_id": "...",
     "attachments": [{"file_id": "..."}]}

  Server → Client: text/event-stream
    event: mode
    data: {"content": {...}, "thread_id": "...", "requested_mode": "...", "resolved_mode": "..."}

    event: token
    data: {"content": "..."}

    event: done
    data: {"thread_id": "...", "content": "", "requested_mode": "...", "resolved_mode": "..."}

    event: error
    data: {"content": "错误信息"}

    event: plan
    data: {"content": [...]}

    event: task
    data: {"content": {...}}

    event: tool
    data: {"content": {...}}
"""

import json

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.schemas import ChatRequest
from src.memory.attachments import (
    AttachmentAccessError,
    AttachmentNotFoundError,
    resolve_attachment_refs_from_db,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _render_plan_text(plan: list[dict], content: str) -> str:
    lines = ["## 计划"]
    for index, item in enumerate(plan, start=1):
        task = str(item.get("content", "")).strip()
        if task:
            lines.append(f"{index}. {task}")
    plan_text = "\n".join(lines) if len(lines) > 1 else ""
    if plan_text and content:
        return f"{plan_text}\n\n## 执行结果\n{content}"
    return plan_text or content


def _sse_event(event_type: str, payload: dict) -> str:
    """格式化单个 SSE 事件。"""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def get_customer_service_supervisor():
    """获取客服编排器。"""
    from src.agent.customer_service import get_customer_service_supervisor as _getter

    return await _getter()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话端点"""
    from src.agent.mode_selector import get_mode_selector
    from src.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    mode_selector = await get_mode_selector()
    customer_service_supervisor = await get_customer_service_supervisor()

    thread_id = request.get_thread_id()
    message = request.message
    user_id = request.user_id
    user_role = request.user_role
    channel = request.channel
    store_id = request.store_id
    mode = request.mode
    attachments = request.attachments

    logger.info(
        "SSE 流式请求",
        thread_id=thread_id,
        user_id=user_id,
        message_preview=message[:50],
    )

    async def generate():
        try:
            resolved_attachments = await resolve_attachment_refs_from_db(
                [a.model_dump() for a in attachments], user_id
            )
        except (AttachmentAccessError, AttachmentNotFoundError) as e:
            yield _sse_event("error", {"content": str(e)})
            return

        from src.memory.conversations import get_conversation_store

        store = get_conversation_store()

        try:
            if user_role == "customer":
                await store.save_user_message(
                    thread_id=thread_id,
                    user_id=user_id,
                    user_role=user_role,
                    message=message,
                    channel=channel,
                    store_id=store_id,
                )
                cs_tokens: list[str] = []
                async for token in customer_service_supervisor.stream(
                    message=message,
                    thread_id=thread_id,
                    user_id=user_id,
                    channel=channel,
                    store_id=store_id,
                ):
                    cs_tokens.append(str(token))
                    yield _sse_event("token", {"content": token})
                try:
                    await store.save_assistant_message(
                        thread_id=thread_id,
                        user_id=user_id,
                        channel=channel,
                        store_id=store_id,
                        content="".join(cs_tokens),
                    )
                except Exception as _exc:
                    logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))
                yield _sse_event("done", {"thread_id": thread_id, "content": ""})
                return

            await store.save_user_message(
                thread_id=thread_id,
                user_id=user_id,
                user_role=user_role,
                message=message,
                channel=channel,
                store_id=store_id,
            )

            mode_decision = await mode_selector.resolve_mode(
                message=message,
                requested_mode=mode,
                attachments=resolved_attachments,
                user_role=user_role,
                channel=channel,
            )
            resolved_mode = str(mode_decision["resolved_mode"])
            yield _sse_event(
                "mode",
                {
                    "content": mode_decision,
                    "thread_id": thread_id,
                    "requested_mode": mode_decision["requested_mode"],
                    "resolved_mode": resolved_mode,
                },
            )

            if resolved_mode == "plan":
                from src.agent.plan_runner import get_plan_runner

                plan_runner = await get_plan_runner()
                rendered_plan: list[dict] = []
                final_tokens: list[str] = []
                done_event: dict = {}
                async for event in plan_runner.stream(
                    message=message,
                    thread_id=thread_id,
                    user_id=user_id,
                    user_role=user_role,
                    channel=channel,
                    store_id=store_id,
                    attachments=resolved_attachments,
                ):
                    event_type = event.get("type", "token")
                    if event_type == "done":
                        done_event = {
                            **event,
                            "requested_mode": mode_decision["requested_mode"],
                            "resolved_mode": resolved_mode,
                        }
                    elif event_type == "plan":
                        rendered_plan = list(event.get("content", []))
                        yield _sse_event(event_type, event)
                    elif event_type == "token":
                        final_tokens.append(str(event.get("content", "")))
                        yield _sse_event(event_type, event)
                    else:
                        yield _sse_event(event_type, event)

                try:
                    await store.save_assistant_message(
                        thread_id=thread_id,
                        user_id=user_id,
                        channel=channel,
                        store_id=store_id,
                        content=_render_plan_text(rendered_plan, "".join(final_tokens)),
                    )
                except Exception as _exc:
                    logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))
                yield _sse_event("done", done_event)
            else:
                final_tokens: list[str] = []
                async for token in orchestrator.stream(
                    message=message,
                    thread_id=thread_id,
                    user_id=user_id,
                    user_role=user_role,
                    channel=channel,
                    store_id=store_id,
                    attachments=resolved_attachments,
                ):
                    final_tokens.append(str(token))
                    yield _sse_event("token", {"content": token})

                try:
                    await store.save_assistant_message(
                        thread_id=thread_id,
                        user_id=user_id,
                        channel=channel,
                        store_id=store_id,
                        content="".join(final_tokens),
                    )
                except Exception as _exc:
                    logger.warning("保存 assistant 消息失败", thread_id=thread_id, error=str(_exc))
                yield _sse_event(
                    "done",
                    {
                        "thread_id": thread_id,
                        "content": "",
                        "requested_mode": mode_decision["requested_mode"],
                        "resolved_mode": resolved_mode,
                    },
                )

        except Exception as e:
            logger.error("SSE 流式处理失败", error=str(e), exc_info=True)
            yield _sse_event("error", {"content": "处理失败，请稍后重试"})

    return StreamingResponse(generate(), media_type="text/event-stream")
