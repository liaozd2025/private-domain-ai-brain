"""OpenAI 兼容适配层。"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()

SUPPORTED_MODELS = {
    "private-domain-auto": "auto",
    "private-domain-chat": "chat",
    "private-domain-plan": "plan",
}
SUPPORTED_IMAGE_SCHEMES = {"http", "https", "data"}


class OpenAIMessage(BaseModel):
    """兼容的 OpenAI 消息结构。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None


class OpenAIChatCompletionRequest(BaseModel):
    """兼容的 Chat Completions 请求。"""

    model: str
    messages: list[OpenAIMessage] = Field(min_length=1)
    stream: bool = False
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    n: int = 1
    logprobs: bool | None = None
    audio: dict[str, Any] | None = None
    modalities: list[str] | None = None
    metadata: dict[str, Any] | None = None


def _reject_unsupported_fields(payload: OpenAIChatCompletionRequest) -> None:
    unsupported_fields = []
    if payload.tools:
        unsupported_fields.append("tools")
    if payload.tool_choice is not None:
        unsupported_fields.append("tool_choice")
    if payload.response_format is not None:
        unsupported_fields.append("response_format")
    if payload.n != 1:
        unsupported_fields.append("n")
    if payload.logprobs is not None:
        unsupported_fields.append("logprobs")
    if payload.audio is not None:
        unsupported_fields.append("audio")
    if payload.modalities is not None:
        unsupported_fields.append("modalities")

    if unsupported_fields:
        fields = ", ".join(unsupported_fields)
        raise HTTPException(status_code=400, detail=f"OpenAI 兼容层暂不支持字段: {fields}")


def _build_messages_prompt(messages: list[tuple[str, str]]) -> str:
    sections = []
    for role, content in messages:
        if not content:
            continue
        sections.append(f"[{role}]\n{content}")
    return "\n\n".join(sections)


def _extract_message_text(message: OpenAIMessage) -> str:
    if isinstance(message.content, str) or message.content is None:
        return (message.content or "").strip()

    parts: list[str] = []
    for part in message.content:
        if part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def _latest_user_text(messages: list[OpenAIMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            text = _extract_message_text(message)
            if text:
                return text
    return ""


def _first_user_text(messages: list[OpenAIMessage]) -> str:
    for message in messages:
        if message.role == "user":
            text = _extract_message_text(message)
            if text:
                return text
    return ""


def _compat_user_role(payload: OpenAIChatCompletionRequest) -> str:
    metadata = payload.metadata or {}
    return str(metadata.get("user_role", "unknown"))


def _compat_thread_id(payload: OpenAIChatCompletionRequest) -> str:
    metadata = payload.metadata or {}
    thread_id = str(metadata.get("thread_id", "")).strip()
    if thread_id:
        return thread_id

    user_id = payload.user or "openai_compat"
    first_user = _first_user_text(payload.messages) or str(uuid.uuid4())
    digest = hashlib.sha1(first_user.encode("utf-8")).hexdigest()[:16]
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:48] or "openai_compat"
    return f"oa_{safe_user}_{digest}"


def _requested_human_handoff(text: str) -> bool:
    keywords = ("人工", "人工客服", "转人工", "真人", "客服")
    normalized = text.strip()
    return any(keyword in normalized for keyword in keywords)


async def get_customer_service_supervisor():
    from src.agent.customer_service import get_customer_service_supervisor as _getter

    return await _getter()


async def get_customer_service_store():
    from src.memory.customer_service import get_customer_service_store as _getter

    return _getter()


async def _should_route_customer_service(
    payload: OpenAIChatCompletionRequest,
    thread_id: str,
) -> bool:
    if _compat_user_role(payload) == "customer":
        return True

    latest_user_text = _latest_user_text(payload.messages)
    if _requested_human_handoff(latest_user_text):
        return True

    if not payload.user and not (payload.metadata or {}).get("thread_id"):
        return False

    store = await get_customer_service_store()
    if await store.get_active_handoff(thread_id):
        return True
    return await store.is_customer_thread(thread_id, user_id=payload.user or "openai_compat")


def _render_plan(plan: list[dict[str, str]]) -> str:
    if not plan:
        return ""

    lines = ["## 计划"]
    status_map = {
        "pending": "待处理",
        "in_progress": "进行中",
        "completed": "已完成",
    }
    for index, item in enumerate(plan, start=1):
        status = status_map.get(item.get("status", "pending"), "待处理")
        content = item.get("content", "").strip()
        if content:
            lines.append(f"{index}. [{status}] {content}")
    return "\n".join(lines).strip()


def _build_plan_content(plan: list[dict[str, str]], content: str) -> str:
    plan_text = _render_plan(plan)
    if plan_text and content:
        return f"{plan_text}\n\n## 执行结果\n{content}"
    if plan_text:
        return plan_text
    return content


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _build_chat_response(model: str, content: str) -> dict[str, Any]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def _build_stream_chunk(
    *,
    completion_id: str,
    model: str,
    content: str = "",
    finish_reason: str | None = None,
    include_role: bool = False,
) -> str:
    delta: dict[str, Any] = {}
    if include_role:
        delta["role"] = "assistant"
    if content:
        delta["content"] = content

    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {_json_dumps(chunk)}\n\n"


def _image_extension_from_mime(mime_type: str | None) -> str:
    if not mime_type:
        return ".bin"
    guessed = mimetypes.guess_extension(mime_type)
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _is_private_host(hostname: str) -> bool:
    """Check if hostname resolves to a private/loopback/reserved IP."""
    import ipaddress
    import socket

    try:
        addrs = socket.getaddrinfo(hostname, None)
        for addr in addrs:
            ip = ipaddress.ip_address(addr[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        return False
    except Exception:
        return True  # Fail safe: block on resolution errors


async def _materialize_image(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in SUPPORTED_IMAGE_SCHEMES:
        raise HTTPException(status_code=400, detail=f"暂不支持的图片协议: {parsed.scheme}")

    image_dir = Path(settings.upload_dir) / "openai_compat"
    image_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex

    if parsed.scheme == "data":
        # Validate data URL format
        if "," not in url:
            raise HTTPException(status_code=400, detail="无效的 data URL 格式")
        header, encoded = url.split(",", maxsplit=1)
        if ":" not in header or ";" not in header:
            raise HTTPException(status_code=400, detail="无效的 data URL 格式")
        mime_type = header.split(":", 1)[1].split(";", 1)[0]
        if not mime_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"不支持的图片格式: {mime_type}")
        try:
            image_data = base64.b64decode(encoded)
        except Exception:
            raise HTTPException(status_code=400, detail="无效的 base64 图片数据")
        if len(image_data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片数据过大（上限 20MB）")
        suffix = _image_extension_from_mime(mime_type)
        file_path = image_dir / f"{file_id}{suffix}"
        file_path.write_bytes(image_data)
    else:
        # SSRF protection: block private/loopback addresses
        hostname = parsed.hostname or ""
        if not hostname or _is_private_host(hostname):
            raise HTTPException(status_code=400, detail="不允许访问内网地址")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        # Limit response size to 10MB
        if len(response.content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片过大（上限 10MB）")

        mime_type = response.headers.get("content-type", "").split(";", 1)[0]
        suffix = Path(parsed.path).suffix or _image_extension_from_mime(mime_type)
        file_path = image_dir / f"{file_id}{suffix}"
        file_path.write_bytes(response.content)

    return {
        "file_id": file_id,
        "filename": file_path.name,
        "file_type": "image",
        "file_path": str(file_path),
    }


async def _translate_messages(
    messages: list[OpenAIMessage],
) -> tuple[str, list[dict[str, Any]]]:
    prompt_messages: list[tuple[str, str]] = []
    attachments: list[dict[str, Any]] = []

    for message in messages:
        if isinstance(message.content, str) or message.content is None:
            prompt_messages.append((message.role, message.content or ""))
            continue

        text_parts: list[str] = []
        for part in message.content:
            part_type = part.get("type")
            if part_type == "text":
                text_parts.append(str(part.get("text", "")))
                continue

            if part_type == "image_url":
                image_url = part.get("image_url", {}).get("url", "")
                if not image_url:
                    raise HTTPException(status_code=400, detail="image_url 缺少 url")
                attachments.append(await _materialize_image(image_url))
                text_parts.append("[附带图片]")
                continue

            raise HTTPException(status_code=400, detail=f"暂不支持的内容片段类型: {part_type}")

        prompt_messages.append((message.role, "\n".join(part for part in text_parts if part)))

    prompt = _build_messages_prompt(prompt_messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="messages 中没有可用文本内容")

    return prompt, attachments


async def _run_non_stream(payload: OpenAIChatCompletionRequest) -> dict[str, Any]:
    prompt, attachments = await _translate_messages(payload.messages)
    user_id = payload.user or "openai_compat"
    thread_id = _compat_thread_id(payload)
    latest_user_text = _latest_user_text(payload.messages) or prompt

    if await _should_route_customer_service(payload, thread_id):
        from src.memory.conversations import record_conversation_turn

        supervisor = await get_customer_service_supervisor()
        result = await supervisor.invoke(
            message=latest_user_text,
            thread_id=thread_id,
            user_id=user_id,
            channel="web",
        )
        await record_conversation_turn(
            thread_id=thread_id,
            user_id=user_id,
            user_role="customer",
            message=latest_user_text,
            channel="web",
        )
        return _build_chat_response(payload.model, result.content)

    mode = await _resolve_mode(
        requested_mode=SUPPORTED_MODELS[payload.model],
        prompt=prompt,
        attachments=attachments,
    )
    if mode == "plan":
        from src.agent.plan_runner import get_plan_runner

        runner = await get_plan_runner()
        result = await runner.invoke(
            message=prompt,
            thread_id=thread_id,
            user_id=user_id,
            user_role="unknown",
            channel="web",
            attachments=attachments,
        )
        content = _build_plan_content(result.plan, result.content)
        return _build_chat_response(payload.model, content)

    from src.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    content = await orchestrator.invoke(
        message=prompt,
        thread_id=thread_id,
        user_id=user_id,
        user_role="unknown",
        channel="web",
        attachments=attachments,
    )
    return _build_chat_response(payload.model, content)


async def _stream_plan_events(
    payload: OpenAIChatCompletionRequest,
    prompt: str,
    attachments: list[dict[str, Any]],
):
    from src.agent.plan_runner import get_plan_runner

    runner = await get_plan_runner()
    thread_id = f"oa_{uuid.uuid4().hex[:16]}"
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    rendered_plan: str | None = None

    yield _build_stream_chunk(
        completion_id=completion_id,
        model=payload.model,
        include_role=True,
    )

    try:
        async for event in runner.stream(
            message=prompt,
            thread_id=thread_id,
            user_id=payload.user or "openai_compat",
            user_role="unknown",
            channel="web",
            attachments=attachments,
        ):
            event_type = event.get("type")
            if event_type in {"plan", "step"}:
                new_plan = _render_plan(event.get("content", []))
                if new_plan and new_plan != rendered_plan:
                    rendered_plan = new_plan
                    yield _build_stream_chunk(
                        completion_id=completion_id,
                        model=payload.model,
                        content=f"{new_plan}\n\n## 执行结果\n",
                    )
                continue
            if event_type == "token":
                yield _build_stream_chunk(
                    completion_id=completion_id,
                    model=payload.model,
                    content=str(event.get("content", "")),
                )
                continue
            if event_type == "done":
                break
    except Exception as exc:
        logger.warning("plan 流式执行失败，降级为 invoke", error=str(exc))
        result = await runner.invoke(
            message=prompt,
            thread_id=thread_id,
            user_id=payload.user or "openai_compat",
            user_role="unknown",
            channel="web",
            attachments=attachments,
        )
        yield _build_stream_chunk(
            completion_id=completion_id,
            model=payload.model,
            content=_build_plan_content(result.plan, result.content),
        )

    yield _build_stream_chunk(
        completion_id=completion_id,
        model=payload.model,
        finish_reason="stop",
    )
    yield "data: [DONE]\n\n"


async def _stream_chat_events(
    payload: OpenAIChatCompletionRequest,
    prompt: str,
    attachments: list[dict[str, Any]],
):
    from src.memory.conversations import record_conversation_turn

    thread_id = _compat_thread_id(payload)
    latest_user_text = _latest_user_text(payload.messages) or prompt
    if await _should_route_customer_service(payload, thread_id):
        supervisor = await get_customer_service_supervisor()
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"

        yield _build_stream_chunk(
            completion_id=completion_id,
            model=payload.model,
            include_role=True,
        )

        async for token in supervisor.stream(
            message=latest_user_text,
            thread_id=thread_id,
            user_id=payload.user or "openai_compat",
            channel="web",
        ):
            yield _build_stream_chunk(
                completion_id=completion_id,
                model=payload.model,
                content=str(token),
            )

        await record_conversation_turn(
            thread_id=thread_id,
            user_id=payload.user or "openai_compat",
            user_role="customer",
            message=latest_user_text,
            channel="web",
        )
        yield _build_stream_chunk(
            completion_id=completion_id,
            model=payload.model,
            finish_reason="stop",
        )
        yield "data: [DONE]\n\n"
        return

    from src.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"

    yield _build_stream_chunk(
        completion_id=completion_id,
        model=payload.model,
        include_role=True,
    )

    async for token in orchestrator.stream(
        message=prompt,
        thread_id=thread_id,
        user_id=payload.user or "openai_compat",
        user_role="unknown",
        channel="web",
        attachments=attachments,
    ):
        yield _build_stream_chunk(
            completion_id=completion_id,
            model=payload.model,
            content=str(token),
        )

    yield _build_stream_chunk(
        completion_id=completion_id,
        model=payload.model,
        finish_reason="stop",
    )
    yield "data: [DONE]\n\n"


async def _resolve_mode(
    *,
    requested_mode: Literal["auto", "chat", "plan"],
    prompt: str,
    attachments: list[dict[str, Any]],
) -> Literal["chat", "plan"]:
    if requested_mode in {"chat", "plan"}:
        return requested_mode

    from src.agent.mode_selector import get_mode_selector

    selector = await get_mode_selector()
    decision = await selector.resolve_mode(
        message=prompt,
        requested_mode="auto",
        attachments=attachments,
        user_role="unknown",
        channel="web",
    )
    return str(decision["resolved_mode"])


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """列出 OpenAI 兼容层可用模型。"""
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": "private-domain-ai-brain",
            }
            for model_id in SUPPORTED_MODELS
        ],
    }


@router.post("/chat/completions")
async def create_chat_completion(payload: OpenAIChatCompletionRequest):
    """OpenAI Chat Completions 兼容端点。"""
    if payload.model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {payload.model}")

    _reject_unsupported_fields(payload)

    if not payload.stream:
        return await _run_non_stream(payload)

    prompt, attachments = await _translate_messages(payload.messages)
    thread_id = _compat_thread_id(payload)
    if await _should_route_customer_service(payload, thread_id):
        generator = _stream_chat_events(payload, prompt, attachments)
        return StreamingResponse(generator, media_type="text/event-stream")

    mode = await _resolve_mode(
        requested_mode=SUPPORTED_MODELS[payload.model],
        prompt=prompt,
        attachments=attachments,
    )
    if mode == "plan":
        generator = _stream_plan_events(payload, prompt, attachments)
    else:
        generator = _stream_chat_events(payload, prompt, attachments)

    return StreamingResponse(generator, media_type="text/event-stream")
