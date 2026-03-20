"""OpenClaw 集成工具

功能：
  - 通过 OpenClaw API 发送消息到各平台
  - 利用 OpenClaw 的 AgentSkills 扩展能力
  - Webhook 接收处理已在 api/webhooks.py 中实现
"""

from typing import Optional

import httpx
import structlog
from langchain_core.tools import tool

from src.config import settings

logger = structlog.get_logger(__name__)


async def _openclaw_request(
    method: str,
    endpoint: str,
    payload: dict = None,
) -> dict:
    """OpenClaw API 请求基础封装"""
    if not settings.openclaw_api_key:
        return {"error": "OpenClaw API Key 未配置"}

    url = f"{settings.openclaw_base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {settings.openclaw_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "POST":
            resp = await client.post(url, headers=headers, json=payload or {})
        else:
            resp = await client.get(url, headers=headers, params=payload or {})

        resp.raise_for_status()
        return resp.json()


@tool
async def send_via_openclaw(
    user_id: str,
    channel: str,
    content: str,
    content_type: str = "text",
) -> str:
    """通过 OpenClaw 向指定用户/渠道发送消息

    Args:
        user_id: 目标用户 ID
        channel: 渠道 (wecom/wechat/sms/email)
        content: 消息内容
        content_type: 内容类型 (text/markdown/html)

    Returns:
        发送结果
    """
    try:
        result = await _openclaw_request(
            "POST",
            "/v1/messages/send",
            {
                "user_id": user_id,
                "channel": channel,
                "content": content,
                "content_type": content_type,
            },
        )
        if "error" in result:
            return f"发送失败: {result['error']}"
        return f"消息已发送至 {channel}/{user_id}"
    except Exception as e:
        return f"发送消息失败: {str(e)}"


@tool
async def query_user_info(user_id: str) -> str:
    """通过 OpenClaw 查询用户信息

    Args:
        user_id: 用户 ID

    Returns:
        用户信息（姓名、标签、历史记录等）
    """
    try:
        result = await _openclaw_request("GET", f"/v1/users/{user_id}")
        if "error" in result:
            return f"查询失败: {result['error']}"

        info = []
        if result.get("name"):
            info.append(f"姓名: {result['name']}")
        if result.get("tags"):
            info.append(f"标签: {', '.join(result['tags'])}")
        if result.get("created_at"):
            info.append(f"创建时间: {result['created_at']}")

        return "\n".join(info) if info else f"用户 {user_id} 的信息: {result}"
    except Exception as e:
        return f"查询用户信息失败: {str(e)}"


@tool
async def broadcast_to_group(
    group_id: str,
    content: str,
    channel: str = "wecom",
) -> str:
    """向群组广播消息

    Args:
        group_id: 群组 ID
        content: 广播内容
        channel: 渠道 (wecom/wechat)

    Returns:
        广播结果
    """
    try:
        result = await _openclaw_request(
            "POST",
            "/v1/groups/broadcast",
            {
                "group_id": group_id,
                "content": content,
                "channel": channel,
            },
        )
        if "error" in result:
            return f"广播失败: {result['error']}"
        return f"消息已广播至群组 {group_id}"
    except Exception as e:
        return f"广播失败: {str(e)}"


class OpenClawToolkit:
    """OpenClaw 工具集合"""

    def get_tools(self) -> list:
        return [send_via_openclaw, query_user_info, broadcast_to_group]
