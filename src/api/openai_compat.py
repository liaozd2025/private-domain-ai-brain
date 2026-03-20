"""OpenAI 兼容适配层。"""

from __future__ import annotations

import base64
import json
import mimetypes
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


async def _materialize_image(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in SUPPORTED_IMAGE_SCHEMES:
        raise HTTPException(status_code=400, detail=f"暂不支持的图片协议: {parsed.scheme}")

    image_dir = Path(settings.upload_dir) / "openai_compat"
    image_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex

    if parsed.scheme == "data":
        header, encoded = url.split(",", maxsplit=1)
        mime_type = header.split(":", 1)[1].split(";", 1)[0]
        suffix = _image_extension_from_mime(mime_type)
        file_path = image_dir / f"{file_id}{suffix}"
        file_path.write_bytes(base64.b64decode(encoded))
    else:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
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
    thread_id = f"oa_{uuid.uuid4().hex[:16]}"

    mode = SUPPORTED_MODELS[payload.model]
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
    from src.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    thread_id = f"oa_{uuid.uuid4().hex[:16]}"
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
    mode = SUPPORTED_MODELS[payload.model]
    if mode == "plan":
        generator = _stream_plan_events(payload, prompt, attachments)
    else:
        generator = _stream_chat_events(payload, prompt, attachments)

    return StreamingResponse(generator, media_type="text/event-stream")
