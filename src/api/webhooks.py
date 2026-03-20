"""Webhook 处理器 - 企微 + OpenClaw

企微 Webhook 流程：
  1. GET 请求：企微验证（echostr 回显）
  2. POST 请求：接收用户消息 → 路由到编排器 → 回复

OpenClaw Webhook 流程：
  接收 OpenClaw 事件 → 解析 → 路由到编排器
"""

import hashlib
import xml.etree.ElementTree as ET

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from src.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()


def _render_plan_text(plan: list[dict[str, str]], content: str) -> str:
    lines = ["## 计划"]
    for index, item in enumerate(plan, start=1):
        task = str(item.get("content", "")).strip()
        if task:
            lines.append(f"{index}. {task}")
    plan_text = "\n".join(lines) if len(lines) > 1 else ""
    if plan_text and content:
        return f"{plan_text}\n\n## 执行结果\n{content}"
    return plan_text or content


# ===== 企微 Webhook =====

def verify_wecom_signature(
    token: str,
    timestamp: str,
    nonce: str,
    echostr: str,
    msg_signature: str,
) -> bool:
    """验证企微消息签名"""
    items = sorted([token, timestamp, nonce, echostr])
    combined = "".join(items)
    computed = hashlib.sha1(combined.encode("utf-8")).hexdigest()
    return computed == msg_signature


@router.get("/wecom")
async def wecom_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """企微 Webhook URL 验证"""
    if not settings.wecom_token:
        raise HTTPException(status_code=503, detail="企微未配置")

    if verify_wecom_signature(
        settings.wecom_token, timestamp, nonce, echostr, msg_signature
    ):
        return int(echostr)
    else:
        raise HTTPException(status_code=403, detail="签名验证失败")


@router.post("/wecom")
async def wecom_receive(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """接收企微消息"""
    if not settings.wecom_token:
        raise HTTPException(status_code=503, detail="企微未配置")

    body = await request.body()

    try:
        root = ET.fromstring(body.decode("utf-8"))
        msg_type = root.findtext("MsgType", "")
        from_user = root.findtext("FromUserName", "")
        content = root.findtext("Content", "")
        agent_id = root.findtext("AgentID", "")

        if msg_type == "text" and content:
            # 后台异步处理，立即返回空响应（企微要求 5s 内响应）
            background_tasks.add_task(
                handle_wecom_message,
                from_user=from_user,
                content=content,
                agent_id=agent_id,
            )

    except Exception as e:
        logger.error("解析企微消息失败", error=str(e))

    return ""  # 企微要求返回空字符串表示成功


async def handle_wecom_message(from_user: str, content: str, agent_id: str):
    """处理企微消息（后台任务）"""
    try:
        from src.agent.mode_selector import get_mode_selector
        from src.agent.orchestrator import get_orchestrator
        from src.agent.plan_runner import get_plan_runner
        from src.memory.conversations import record_conversation_turn

        mode_selector = await get_mode_selector()
        orchestrator = await get_orchestrator()

        thread_id = f"wecom_{from_user}"
        mode_decision = await mode_selector.resolve_mode(
            message=content,
            requested_mode="auto",
            user_role="unknown",
            channel="wecom",
        )
        if mode_decision["resolved_mode"] == "plan":
            plan_runner = await get_plan_runner()
            result = await plan_runner.invoke(
                message=content,
                thread_id=thread_id,
                user_id=from_user,
                channel="wecom",
            )
            response = _render_plan_text(result.plan, result.content)
        else:
            response = await orchestrator.invoke(
                message=content,
                thread_id=thread_id,
                user_id=from_user,
                channel="wecom",
            )
        await record_conversation_turn(
            thread_id=thread_id,
            user_id=from_user,
            message=content,
            channel="wecom",
        )

        await send_wecom_message(to_user=from_user, content=response)
        logger.info("企微消息处理完成", from_user=from_user)

    except Exception as e:
        logger.error("处理企微消息失败", from_user=from_user, error=str(e))


async def send_wecom_message(to_user: str, content: str):
    """发送企微消息"""
    if not settings.wecom_secret:
        logger.warning("企微 Secret 未配置，跳过发送")
        return

    # 获取 access_token
    async with httpx.AsyncClient() as client:
        token_resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={
                "corpid": settings.wecom_corp_id,
                "corpsecret": settings.wecom_secret,
            },
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            logger.error("获取企微 access_token 失败", data=token_data)
            return

        # 发送消息
        await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
            json={
                "touser": to_user,
                "msgtype": "text",
                "agentid": settings.wecom_agent_id,
                "text": {"content": content},
                "safe": 0,
            },
        )


# ===== OpenClaw Webhook =====

@router.post("/openclaw")
async def openclaw_receive(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """接收 OpenClaw 事件"""
    try:
        payload = await request.json()
        event_type = payload.get("event_type", "")
        user_id = payload.get("user_id", "")
        message = payload.get("message", "")
        channel = payload.get("channel", "openclaw")

        if event_type == "message" and message:
            background_tasks.add_task(
                handle_openclaw_message,
                user_id=user_id,
                message=message,
                channel=channel,
                metadata=payload.get("metadata", {}),
            )

        return {"status": "received"}

    except Exception as e:
        logger.error("解析 OpenClaw Webhook 失败", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


async def handle_openclaw_message(
    user_id: str,
    message: str,
    channel: str,
    metadata: dict,
):
    """处理 OpenClaw 消息（后台任务）"""
    try:
        from src.agent.mode_selector import get_mode_selector
        from src.agent.orchestrator import get_orchestrator
        from src.agent.plan_runner import get_plan_runner
        from src.memory.conversations import record_conversation_turn

        mode_selector = await get_mode_selector()
        orchestrator = await get_orchestrator()

        thread_id = f"openclaw_{user_id}_{channel}"
        mode_decision = await mode_selector.resolve_mode(
            message=message,
            requested_mode="auto",
            user_role="unknown",
            channel="openclaw",
        )
        if mode_decision["resolved_mode"] == "plan":
            plan_runner = await get_plan_runner()
            result = await plan_runner.invoke(
                message=message,
                thread_id=thread_id,
                user_id=user_id,
                channel="openclaw",
            )
            response = _render_plan_text(result.plan, result.content)
        else:
            response = await orchestrator.invoke(
                message=message,
                thread_id=thread_id,
                user_id=user_id,
                channel="openclaw",
            )
        await record_conversation_turn(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            channel="openclaw",
        )

        # 通过 OpenClaw API 回复
        if settings.openclaw_api_key:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{settings.openclaw_base_url}/v1/messages/reply",
                    headers={"Authorization": f"Bearer {settings.openclaw_api_key}"},
                    json={
                        "user_id": user_id,
                        "channel": channel,
                        "content": response,
                        "metadata": metadata,
                    },
                )

        logger.info("OpenClaw 消息处理完成", user_id=user_id)

    except Exception as e:
        logger.error("处理 OpenClaw 消息失败", user_id=user_id, error=str(e))
