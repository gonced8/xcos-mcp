# SPDX-License-Identifier: GPL-3.0-only
"""Runtime configuration and filesystem policy."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


def runtime_dir() -> Path:
    default = PROJECT_ROOT / ".xcos-mcp" if (PROJECT_ROOT / "pyproject.toml").is_file() else Path.cwd() / ".xcos-mcp"
    return Path(os.environ.get("XCOS_RUNTIME_DIR", default)).expanduser().resolve()


def artifact_dir() -> Path:
    return Path(os.environ.get("XCOS_ARTIFACT_DIR", runtime_dir() / "artifacts")).expanduser().resolve()


def allowed_model_roots() -> tuple[Path, ...]:
    configured = os.environ.get("XCOS_ALLOWED_MODEL_ROOTS", "")
    if configured:
        configured_roots = tuple(
            Path(value).expanduser().resolve()
            for value in configured.split(os.pathsep)
            if value.strip()
        )
        return tuple(dict.fromkeys((*configured_roots, artifact_dir())))
    roots = [Path.cwd().resolve()]
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        roots.append(PROJECT_ROOT)
    return tuple(dict.fromkeys((*roots, artifact_dir())))


def ensure_allowed(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not any(resolved == root or root in resolved.parents for root in allowed_model_roots()):
        roots = [str(root) for root in allowed_model_roots()]
        raise ValueError(f"Path is outside XCOS_ALLOWED_MODEL_ROOTS: {resolved}; allowed roots: {roots}")
    return resolved
