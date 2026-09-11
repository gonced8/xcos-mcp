# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import zipfile

import pytest

from scripts.check_wheel import LFS_MARKER, REQUIRED_SUFFIXES, check_wheel


def _wheel(path: Path, extra: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in REQUIRED_SUFFIXES:
            archive.writestr(name, b"source")
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return path


def test_source_only_wheel_passes(tmp_path: Path):
    check_wheel(_wheel(tmp_path / "valid.whl"))


def test_bundled_runtime_resource_fails(tmp_path: Path):
    candidate = _wheel(tmp_path / "resources.whl", {"xcos_mcp/resources/copied.sci": b"x"})
    with pytest.raises(RuntimeError, match="bundled runtime"):
        check_wheel(candidate)


def test_lfs_pointer_fails(tmp_path: Path):
    candidate = _wheel(tmp_path / "pointer.whl", {"xcos_mcp/extra.txt": LFS_MARKER})
    with pytest.raises(RuntimeError, match="LFS"):
        check_wheel(candidate)
