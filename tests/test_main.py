"""应用启动前置校验测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.main import ensure_upload_dir_ready


def test_ensure_upload_dir_ready_creates_oss_cache(tmp_path):
    upload_root = tmp_path / "uploads"

    with patch("src.main.settings.upload_dir", str(upload_root)):
        ensure_upload_dir_ready()

    assert upload_root.exists()
    assert (upload_root / "oss_cache").exists()
    assert not (upload_root / "oss_cache" / ".write_probe").exists()


def test_ensure_upload_dir_ready_raises_when_upload_dir_not_writable(tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True)
    oss_cache_dir = upload_root / "oss_cache"
    oss_cache_dir.mkdir()

    original_write_bytes = Path.write_bytes

    def _deny_write(self: Path, data: bytes) -> int:
        if self == oss_cache_dir / ".write_probe":
            raise PermissionError("permission denied")
        return original_write_bytes(self, data)

    with (
        patch("src.main.settings.upload_dir", str(upload_root)),
        patch.object(Path, "write_bytes", _deny_write),
    ):
        with pytest.raises(RuntimeError, match="UPLOAD_DIR 不可写"):
            ensure_upload_dir_ready()
