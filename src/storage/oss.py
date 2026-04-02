"""阿里云 OSS 文件存储客户端"""

from __future__ import annotations

import importlib
import io
from pathlib import Path
from typing import Any

from src.config import settings


class OSSStorageError(RuntimeError):
    """OSS 存储异常。"""


def _get_oss2() -> Any:
    """懒加载 oss2，避免缺少可选依赖时阻塞整个服务启动。"""
    try:
        return importlib.import_module("oss2")
    except ModuleNotFoundError as exc:
        raise OSSStorageError("缺少 oss2 依赖，请重建镜像或安装 oss2 后再使用 OSS 功能") from exc


def _get_bucket():
    oss2 = _get_oss2()
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket_name)


def build_object_key(user_id: str, file_id: str, suffix: str) -> str:
    """构造 OSS 对象 key，格式：{prefix}/{user_id}/{file_id}{suffix}"""
    prefix = settings.oss_prefix.rstrip("/")
    return f"{prefix}/{user_id}/{file_id}{suffix}"


def upload_bytes(
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """上传字节数据到 OSS，返回 object_key"""
    bucket = _get_bucket()
    try:
        bucket.put_object(
            object_key,
            io.BytesIO(data),
            headers={"Content-Type": content_type},
        )
    except Exception as exc:
        raise OSSStorageError(f"OSS 上传失败: {exc}") from exc
    return object_key


def download_to_tempfile(object_key: str) -> str:
    """从 OSS 下载对象到本地临时文件，返回临时文件路径（调用方负责清理）"""
    suffix = Path(object_key).suffix
    from tempfile import NamedTemporaryFile

    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    return download_to_path(object_key, tmp.name)


def download_to_path(object_key: str, destination_path: str | Path) -> str:
    """从 OSS 下载对象到指定本地路径，返回目标路径。"""
    bucket = _get_bucket()
    try:
        result = bucket.get_object(object_key)
        data = result.read()
    except Exception as exc:
        raise OSSStorageError(f"OSS 下载失败: {exc}") from exc

    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return str(destination)
