# SPDX-License-Identifier: GPL-3.0-only
"""Audit a built xcos-mcp wheel for a complete, source-only distribution."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


REQUIRED_SUFFIXES = {
    "xcos_mcp/server.py",
    "xcos_mcp/process.py",
    "xcos_mcp/model.py",
    "xcos_mcp/catalog.py",
    "xcos_mcp/simulation.py",
}
LFS_MARKER = b"version https://git-lfs.github.com/spec/v1"


def check_wheel(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        missing = sorted(REQUIRED_SUFFIXES - names)
        if missing:
            raise RuntimeError(f"Wheel is missing required resources: {missing}")

        forbidden = sorted(name for name in names if "/resources/" in name)
        if forbidden:
            raise RuntimeError(f"Wheel contains bundled runtime resources: {forbidden[:10]}")

        placeholders = sorted(
            name for name in names
            if not name.endswith("/") and wheel.read(name).startswith(LFS_MARKER)
        )
        if placeholders:
            raise RuntimeError(f"Wheel contains Git LFS pointer placeholders: {placeholders}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    check_wheel(args.wheel)
    print(f"Wheel audit passed: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
