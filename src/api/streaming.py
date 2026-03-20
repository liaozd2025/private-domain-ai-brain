"""WebSocket 流式端点

支持 token-by-token 实时流式响应，适合前端聊天界面。

协议：
  Client → Server:
    {"message": "...", "thread_id": "...", "user_id": "...", "user_role": "...",
     "attachments": [{"file_id": "..."}]}
  Server → Client: {"type": "token", "content": "..."}  (多次)
                   {"type": "done", "thread_id": "...", "query_type": "..."}
                   {"type": "error", "content": "错误信息"}
"""

import json
from uuid import uuid4

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.memory.attachments import (
    AttachmentAccessError,
    AttachmentNotFoundError,
    resolve_attachment_refs,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.websocket("/chat/stream")
async def chat_stream(websocket: WebSocket):
    """WebSocket 流式对话端点"""
    await websocket.accept()
    logger.info("WebSocket 连接建立")

    try:
        from src.agent.orchestrator import get_orchestrator
        orchestrator = await get_orchestrator()

        while True:
            # 接收消息
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "无效的 JSON 格式"})
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"type": "error", "content": "消息不能为空"})
                continue

            thread_id = data.get("thread_id") or f"thread_{uuid4().hex[:16]}"
            user_id = data.get("user_id", "anonymous")
            user_role = data.get("user_role", "unknown")
            channel = data.get("channel", "web")
            mode = data.get("mode", "chat")
            attachments = data.get("attachments", [])

            logger.info(
                "WebSocket 消息",
                thread_id=thread_id,
                user_id=user_id,
                message_preview=message[:50],
            )

            # 流式输出
            try:
                resolved_attachments = resolve_attachment_refs(attachments, user_id)
                if mode == "plan":
                    from src.agent.plan_runner import get_plan_runner
                    from src.memory.conversations import record_conversation_turn

                    plan_runner = await get_plan_runner()
                    async for event in plan_runner.stream(
                        message=message,
                        thread_id=thread_id,
                        user_id=user_id,
                        user_role=user_role,
                        channel=channel,
                        attachments=resolved_attachments,
                    ):
                        await websocket.send_json(event)
                    await record_conversation_turn(
                        thread_id=thread_id,
                        user_id=user_id,
                        message=message,
                        channel=channel,
                    )
                else:
                    from src.memory.conversations import record_conversation_turn

                    async for token in orchestrator.stream(
                        message=message,
                        thread_id=thread_id,
                        user_id=user_id,
                        user_role=user_role,
                        channel=channel,
                        attachments=resolved_attachments,
                    ):
                        await websocket.send_json({"type": "token", "content": token})

                    # 发送完成信号
                    await websocket.send_json({
                        "type": "done",
                        "thread_id": thread_id,
                        "content": "",
                    })
                    await record_conversation_turn(
                        thread_id=thread_id,
                        user_id=user_id,
                        message=message,
                        channel=channel,
                    )

            except (AttachmentAccessError, AttachmentNotFoundError) as e:
                await websocket.send_json({"type": "error", "content": str(e)})
            except Exception as e:
                logger.error("流式处理失败", error=str(e))
                await websocket.send_json({"type": "error", "content": f"处理失败: {str(e)}"})

    except WebSocketDisconnect:
        logger.info("WebSocket 连接断开")
    except Exception as e:
        logger.error("WebSocket 异常", error=str(e))
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
