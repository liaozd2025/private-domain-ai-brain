"""附件解析与 OSS 物化测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.memory.attachments import (
    AttachmentStorageError,
    materialize_attachment_from_oss,
    resolve_attachment_refs_from_db,
)
from src.storage.oss import OSSStorageError


class _FakeMappingsResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeExecuteResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _FakeMappingsResult(self._row)


class _FakeConnection:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query):
        return _FakeExecuteResult(self._row)


class _FakeEngine:
    def __init__(self, row):
        self._row = row

    def connect(self):
        return _FakeConnection(self._row)


def test_materialize_attachment_from_oss_uses_upload_dir_cache_path(tmp_path):
    """OSS 物化后的附件路径必须落在 upload_dir/oss_cache 下。"""
    upload_root = tmp_path / "uploads"

    with (
        patch("src.config.settings.upload_dir", str(upload_root)),
        patch("src.storage.oss.download_to_path") as mock_download,
    ):
        materialize_attachment_from_oss(
            object_key="uploads/user1/file_sales_001.csv",
            file_id="file_sales_001",
            user_id="user1",
            suffix=".csv",
        )

    mock_download.assert_called_once_with(
        "uploads/user1/file_sales_001.csv",
        upload_root / "oss_cache" / "user1" / "file_sales_001.csv",
    )


@pytest.mark.asyncio
async def test_resolve_attachment_refs_from_db_materializes_from_oss_cache(tmp_path):
    """附件解析应把 OSS key 物化成 upload_dir/oss_cache 下的本地路径。"""
    upload_root = tmp_path / "uploads"
    row = {
        "file_id": "file_sales_001",
        "user_id": "user1",
        "filename": "sales.csv",
        "file_type": "csv",
        "file_path": "uploads/user1/file_sales_001.csv",
    }
    resolved_path = upload_root / "oss_cache" / "user1" / "file_sales_001.csv"

    with (
        patch("src.config.settings.upload_dir", str(upload_root)),
        patch("src.memory.db.get_async_engine", return_value=_FakeEngine(row)),
        patch(
            "src.memory.attachments.materialize_attachment_from_oss",
            return_value=str(resolved_path),
        ) as mock_materialize,
    ):
        attachments = await resolve_attachment_refs_from_db(
            [{"file_id": "file_sales_001"}],
            "user1",
        )

    assert attachments == [
        {
            "file_id": "file_sales_001",
            "user_id": "user1",
            "filename": "sales.csv",
            "file_type": "csv",
            "file_path": str(resolved_path),
        }
    ]
    mock_materialize.assert_called_once_with(
        object_key="uploads/user1/file_sales_001.csv",
        file_id="file_sales_001",
        user_id="user1",
        suffix=".csv",
    )


@pytest.mark.asyncio
async def test_resolve_attachment_refs_from_db_maps_oss_failures_to_storage_error():
    """OSS 回读失败时不应伪装成附件不存在。"""
    row = {
        "file_id": "file_sales_001",
        "user_id": "user1",
        "filename": "sales.csv",
        "file_type": "csv",
        "file_path": "uploads/user1/file_sales_001.csv",
    }

    with (
        patch("src.memory.db.get_async_engine", return_value=_FakeEngine(row)),
        patch(
            "src.memory.attachments.materialize_attachment_from_oss",
            side_effect=OSSStorageError("OSS 下载失败: timeout"),
        ),
    ):
        with pytest.raises(AttachmentStorageError, match="附件存储服务暂时不可用"):
            await resolve_attachment_refs_from_db([{"file_id": "file_sales_001"}], "user1")
