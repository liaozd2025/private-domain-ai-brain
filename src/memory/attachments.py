"""附件元数据持久化与解析"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import settings


class AttachmentError(Exception):
    """附件处理基础异常"""


class AttachmentNotFoundError(AttachmentError):
    """附件不存在"""


class AttachmentAccessError(AttachmentError):
    """附件访问越权"""


def _metadata_dir() -> Path:
    metadata_dir = Path(settings.upload_dir) / "_meta"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    return metadata_dir


def save_attachment_metadata(
    *,
    file_id: str,
    user_id: str,
    filename: str,
    file_type: str,
    file_path: str,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """保存附件元数据"""
    metadata = {
        "file_id": file_id,
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "file_path": file_path,
        "thread_id": thread_id,
    }
    metadata_path = _metadata_dir() / f"{file_id}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def get_attachment_metadata(file_id: str) -> dict[str, Any]:
    """读取单个附件元数据"""
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", file_id):
        raise AttachmentNotFoundError(f"无效的附件 ID: {file_id}")
    metadata_path = _metadata_dir() / f"{file_id}.json"
    if not metadata_path.exists():
        raise AttachmentNotFoundError(f"附件不存在: {file_id}")

    return json.loads(metadata_path.read_text(encoding="utf-8"))


def resolve_attachment_ref(ref: dict[str, Any], user_id: str) -> dict[str, Any]:
    """根据 file_id 解析服务端附件信息"""
    file_id = ref.get("file_id", "").strip()
    if not file_id:
        raise AttachmentNotFoundError("附件缺少 file_id")

    metadata = get_attachment_metadata(file_id)
    metadata_user_id = metadata.get("user_id", "")
    if metadata_user_id and metadata_user_id != user_id:
        raise AttachmentAccessError(f"无权访问附件: {file_id}")

    file_path = metadata.get("file_path", "")
    if not file_path or not Path(file_path).exists():
        raise AttachmentNotFoundError(f"附件文件不存在或已被删除: {file_id}")

    return metadata


def resolve_attachment_refs(refs: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
    """批量解析附件引用"""
    return [resolve_attachment_ref(ref, user_id) for ref in refs]


async def resolve_attachment_refs_from_db(
    refs: list[dict[str, Any]],
    user_id: str,
) -> list[dict[str, Any]]:
    """从 uploaded_files 表解析附件引用，找不到时 fallback 到文件系统 JSON。"""
    from sqlalchemy import select

    from src.memory.db import get_async_engine, uploaded_files_table

    results = []
    async with get_async_engine().connect() as conn:
        for ref in refs:
            file_id = ref.get("file_id", "").strip()
            if not file_id:
                raise AttachmentNotFoundError("附件缺少 file_id")

            row = (
                await conn.execute(
                    select(uploaded_files_table).where(
                        uploaded_files_table.c.file_id == file_id
                    )
                )
            ).mappings().first()

            if row is None:
                # fallback：兼容 DB 写入前的历史上传
                metadata = get_attachment_metadata(file_id)
                if metadata.get("user_id") and metadata["user_id"] != user_id:
                    raise AttachmentAccessError(f"无权访问附件: {file_id}")
            else:
                metadata = dict(row)
                if metadata.get("user_id") and metadata["user_id"] != user_id:
                    raise AttachmentAccessError(f"无权访问附件: {file_id}")

            file_path = metadata.get("file_path", "")
            if not file_path or not Path(file_path).exists():
                raise AttachmentNotFoundError(f"附件文件不存在或已被删除: {file_id}")

            results.append(metadata)
    return results
