# SPDX-License-Identifier: GPL-3.0-only
"""Discover Xcos block definitions from the installed Scilab tree."""

from __future__ import annotations

from pathlib import Path
import re
import uuid

from .config import artifact_dir
from .model import inspect_model
from .process import run_scilab_script, scilab_root, wait_for_files


BLOCK_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _macro_root() -> Path:
    root = scilab_root()
    if root is None:
        raise RuntimeError("Scilab is not installed or configured")
    candidates = (
        root / "share" / "scilab" / "modules" / "scicos_blocks" / "macros",
        root / "modules" / "scicos_blocks" / "macros",
    )
    macros = next((candidate for candidate in candidates if candidate.is_dir()), None)
    if macros is None:
        raise RuntimeError(f"Xcos block macros were not found under {root}")
    return macros


def list_blocks(query: str = "", limit: int = 100) -> dict[str, object]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    needle = query.casefold().strip()
    records: list[dict[str, str]] = []
    root = _macro_root()
    for source in sorted(root.rglob("*.sci")):
        name = source.stem
        if not BLOCK_NAME.fullmatch(name) or needle not in name.casefold():
            continue
        records.append({"name": name, "category": source.parent.name, "source_path": str(source)})
        if len(records) == limit:
            break
    return {"success": True, "query": query, "count": len(records), "blocks": records}


def block_source(name: str) -> dict[str, object]:
    if not BLOCK_NAME.fullmatch(name):
        raise ValueError("name must be a valid Scilab identifier")
    matches = [path for path in _macro_root().rglob(f"{name}.sci") if path.stem == name]
    if not matches:
        raise ValueError(f"Unknown Xcos block: {name}")
    source = matches[0]
    content = source.read_text(encoding="utf-8", errors="replace")
    return {"success": True, "name": name, "source_path": str(source), "source": content}


def create_block_template(name: str, timeout_seconds: float = 120.0) -> dict[str, object]:
    # Confirm membership before interpolating a validated identifier into Scilab code.
    block_source(name)
    output_dir = artifact_dir() / "templates" / uuid.uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / f"{name}.xcos"
    script = f'''mode(-1);
lines(0);
loadXcosLibs();
loadScicos();
scs_m = scicos_diagram();
scs_m.objs(1) = {name}("define");
scs_m.objs(1).graphics.orig = [20 20];
xcosDiagramToScilab(getenv("XCOS_MCP_TEMPLATE_PATH"), scs_m);
exit(0);
'''
    result = run_scilab_script(
        script,
        timeout_seconds,
        gui=True,
        environment={"XCOS_MCP_TEMPLATE_PATH": str(output_path)},
    )
    if not wait_for_files([output_path]):
        raise RuntimeError(f"Xcos did not export the requested block template: {result.output[-2000:]}")
    structure = inspect_model(str(output_path))
    return {
        "success": True,
        "name": name,
        "model_path": str(output_path),
        "xml_content": output_path.read_text(encoding="utf-8"),
        "structure": structure,
    }
