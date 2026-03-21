"""Webhook 处理器 - 企微 + OpenClaw

企微 Webhook 流程：
  1. GET 请求：企微验证（echostr 回显）
  2. POST 请求：接收用户消息 → 路由到编排器 → 回复

OpenClaw Webhook 流程：
  接收 OpenClaw 事件 → 解析 → 路由到编排器
"""

import hashlib
import time

import defusedxml.ElementTree as ET
import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from src.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()

# ===== 共享 HTTP 客户端 =====

_http_client: httpx.AsyncClient | None = None

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


# ===== 企微 Access Token 缓存 =====

_wecom_access_token: str | None = None
_wecom_token_expires_at: float = 0.0
_WECOM_TOKEN_TTL = 6000  # 缓存 6000s（有效期 7200s）


async def _get_wecom_access_token() -> str | None:
    """获取企微 access_token（带 TTL 缓存）"""
    global _wecom_access_token, _wecom_token_expires_at

    now = time.monotonic()
    if _wecom_access_token and now < _wecom_token_expires_at:
        return _wecom_access_token

    client = _get_http_client()
    try:
        token_resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={
                "corpid": settings.wecom_corp_id,
                "corpsecret": settings.wecom_secret,
            },
        )
        token_data = token_resp.json()
    except Exception as e:
        logger.error("获取企微 access_token 请求失败", error=str(e))
        return None

    token = token_data.get("access_token")
    if token:
        _wecom_access_token = token
        _wecom_token_expires_at = now + _WECOM_TOKEN_TTL
    else:
        logger.error("获取企微 access_token 失败", data=token_data)

    return token


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
    except Exception as e:
        logger.error("解析企微消息 XML 失败", error=str(e))
        raise HTTPException(status_code=400, detail="无效的消息格式")

    # 签名校验：使用 Encrypt 字段
    encrypt = root.findtext("Encrypt", "")
    if not verify_wecom_signature(
        settings.wecom_token, timestamp, nonce, encrypt, msg_signature
    ):
        raise HTTPException(status_code=403, detail="签名验证失败")

    try:
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
        logger.error("处理企微消息失败", error=str(e))

    return ""  # 企微要求返回空字符串表示成功


async def handle_wecom_message(from_user: str, content: str, agent_id: str):
    """处理企微消息（后台任务）"""
    try:
        from src.agent.customer_service import get_customer_service_supervisor
        from src.memory.conversations import record_conversation_turn

        thread_id = f"wecom_{from_user}"
        customer_service_supervisor = await get_customer_service_supervisor()
        result = await customer_service_supervisor.invoke(
            message=content,
            thread_id=thread_id,
            user_id=from_user,
            channel="wecom",
        )
        await record_conversation_turn(
            thread_id=thread_id,
            user_id=from_user,
            user_role="customer",
            message=content,
            channel="wecom",
        )

        await send_wecom_message(to_user=from_user, content=result.content)
        logger.info("企微消息处理完成", from_user=from_user)

    except Exception as e:
        logger.error("处理企微消息失败", from_user=from_user, error=str(e))


async def send_wecom_message(to_user: str, content: str):
    """发送企微消息"""
    if not settings.wecom_secret:
        logger.warning("企微 Secret 未配置，跳过发送")
        return

    access_token = await _get_wecom_access_token()
    if not access_token:
        return

    client = _get_http_client()
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
        raise HTTPException(status_code=400, detail="无效的请求格式")


async def handle_openclaw_message(
    user_id: str,
    message: str,
    channel: str,
    metadata: dict,
):
    """处理 OpenClaw 消息（后台任务）"""
    try:
        from src.agent.customer_service import get_customer_service_supervisor
        from src.agent.orchestrator import get_orchestrator
        from src.memory.conversations import record_conversation_turn

        thread_id = f"openclaw_{user_id}_{channel}"
        user_role = str(metadata.get("user_role", "customer"))
        if user_role == "customer":
            customer_service_supervisor = await get_customer_service_supervisor()
            result = await customer_service_supervisor.invoke(
                message=message,
                thread_id=thread_id,
                user_id=user_id,
                channel=channel,
            )
            response = result.content
        else:
            orchestrator = await get_orchestrator()
            response = await orchestrator.invoke(
                message=message,
                thread_id=thread_id,
                user_id=user_id,
                user_role=user_role,
                channel=channel,
            )
        await record_conversation_turn(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            message=message,
            channel=channel,
        )

        # 通过 OpenClaw API 回复
        await send_openclaw_message(
            user_id=user_id,
            channel=channel,
            content=response,
            metadata=metadata,
        )

        logger.info("OpenClaw 消息处理完成", user_id=user_id)

    except Exception as e:
        logger.error("处理 OpenClaw 消息失败", user_id=user_id, error=str(e))


async def send_openclaw_message(
    *,
    user_id: str,
    channel: str,
    content: str,
    metadata: dict | None = None,
):
    """发送 OpenClaw 消息。"""
    if not settings.openclaw_api_key:
        return

    client = _get_http_client()
    await client.post(
        f"{settings.openclaw_base_url}/v1/messages/reply",
        headers={"Authorization": f"Bearer {settings.openclaw_api_key}"},
        json={
            "user_id": user_id,
            "channel": channel,
            "content": content,
            "metadata": metadata or {},
        },
    )
