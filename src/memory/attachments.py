"""附件元数据持久化与解析"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class AttachmentError(Exception):
    """附件处理基础异常"""


class AttachmentNotFoundError(AttachmentError):
    """附件不存在"""


class AttachmentAccessError(AttachmentError):
    """附件访问越权"""


class AttachmentStorageError(AttachmentError):
    """附件存储不可用"""


def materialize_attachment_from_oss(
    *,
    object_key: str,
    file_id: str,
    user_id: str,
    suffix: str,
) -> str:
    """把 OSS 对象物化到 upload_dir 下的受控缓存路径。"""
    from src.storage.oss import download_to_path

    safe_user_id = user_id.strip() or "anonymous"
    safe_suffix = suffix or Path(object_key).suffix
    cache_path = (
        Path(settings.upload_dir).resolve()
        / "oss_cache"
        / safe_user_id
        / f"{file_id}{safe_suffix}"
    )
    return download_to_path(object_key, cache_path)


async def resolve_attachment_refs_from_db(
    refs: list[dict[str, Any]],
    user_id: str,
) -> list[dict[str, Any]]:
    """从 uploaded_files 表解析附件引用，从 OSS 下载到受控缓存目录后返回本地路径。"""
    if not refs:
        return []

    from sqlalchemy import select

    from src.memory.db import get_async_engine, uploaded_files_table
    from src.storage.oss import OSSStorageError

    results = []
    async with get_async_engine().connect() as conn:
        for ref in refs:
            file_id = ref.get("file_id", "").strip()
            if not file_id:
                raise AttachmentNotFoundError("附件缺少 file_id")

            logger.debug("解析附件引用", file_id=file_id, request_user_id=repr(user_id))

            row = (
                await conn.execute(
                    select(uploaded_files_table).where(
                        uploaded_files_table.c.file_id == file_id
                    )
                )
            ).mappings().first()

            if row is None:
                raise AttachmentNotFoundError(f"附件不存在: {file_id}")

            metadata = dict(row)
            stored_uid = metadata.get("user_id")
            logger.debug(
                "附件所有权校验",
                file_id=file_id,
                stored_user_id=repr(stored_uid),
                request_user_id=repr(user_id),
                match=(stored_uid == user_id),
            )
            if stored_uid and stored_uid != user_id:
                raise AttachmentAccessError(f"无权访问附件: {file_id}")

            object_key = metadata.get("file_path", "")
            if not object_key:
                raise AttachmentNotFoundError(f"附件 OSS key 为空: {file_id}")

            try:
                local_path = await anyio.to_thread.run_sync(
                    lambda key=object_key, attachment_file_id=file_id, request_user_id=user_id: (
                        materialize_attachment_from_oss(
                            object_key=key,
                            file_id=attachment_file_id,
                            user_id=request_user_id,
                            suffix=Path(key).suffix,
                        )
                    )
                )
            except OSSStorageError as e:
                raise AttachmentStorageError(
                    f"附件存储服务暂时不可用: {file_id}"
                ) from e

            metadata["file_path"] = local_path
            results.append(metadata)

    return results
