# SPDX-License-Identifier: GPL-3.0-only
"""Xcos model path policy, XML inspection, persistence, and real validation."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

from .config import PROJECT_ROOT, ensure_allowed
from .process import run_scilab_script, scilab_string, wait_for_files


LINK_TAGS = {"ExplicitLink", "CommandControlLink", "ImplicitLink"}
DEFAULT_MAX_MODEL_BYTES = 16 * 1024 * 1024


def _max_model_bytes() -> int:
    try:
        limit = int(os.environ.get("XCOS_MAX_MODEL_BYTES", str(DEFAULT_MAX_MODEL_BYTES)))
    except ValueError as exc:
        raise ValueError("XCOS_MAX_MODEL_BYTES must be a positive integer") from exc
    if limit <= 0:
        raise ValueError("XCOS_MAX_MODEL_BYTES must be a positive integer")
    return limit


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def resolve_model_path(model_path: str) -> Path:
    requested = Path(model_path).expanduser()
    candidates = [requested.resolve()] if requested.is_absolute() else [
        (Path.cwd() / requested).resolve(),
        (PROJECT_ROOT / requested).resolve(),
    ]
    candidate = next((item for item in candidates if item.is_file()), candidates[0])
    ensure_allowed(candidate)
    if candidate.suffix.lower() != ".xcos" or not candidate.is_file():
        raise ValueError("model_path must name an existing .xcos file")
    return candidate


def resolve_output_path(output_path: str) -> Path:
    requested = Path(output_path).expanduser()
    candidate = requested.resolve() if requested.is_absolute() else (Path.cwd() / requested).resolve()
    ensure_allowed(candidate)
    if candidate.suffix.lower() != ".xcos":
        raise ValueError("output_path must end in .xcos")
    return candidate


def parse_xcos(source: str | Path) -> tuple[Path, ET.Element]:
    path = resolve_model_path(str(source))
    limit = _max_model_bytes()
    if path.stat().st_size > limit:
        raise ValueError(f"Xcos model exceeds the {limit} byte limit")
    root = ET.parse(path).getroot()
    if _local_name(root.tag) != "XcosDiagram":
        raise ValueError("XML root must be XcosDiagram")
    return path, root


def recorded_outputs(root: ET.Element) -> list[str]:
    outputs: list[str] = []
    for block in root.iter():
        if block.attrib.get("interfaceFunctionName") != "TOWS_c":
            continue
        expressions = next((child for child in block if child.attrib.get("as") == "exprs"), None)
        if expressions is None:
            continue
        values = {
            int(item.attrib["line"]): item.attrib.get("value", "")
            for item in expressions
            if _local_name(item.tag) == "data" and item.attrib.get("line", "").isdigit()
        }
        name = values.get(1, "")
        if name and name not in outputs:
            outputs.append(name)
    return outputs


def structural_issues(root: ET.Element) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    ids: set[str] = set()
    duplicates: set[str] = set()
    for element in root.iter():
        identifier = element.attrib.get("id")
        if not identifier:
            continue
        # Xcos serializes some mxCell defaults twice by design. Only executable
        # graph objects must have unique identities.
        is_graph_object = bool(element.attrib.get("interfaceFunctionName")) or _local_name(element.tag) in LINK_TAGS
        if is_graph_object and identifier in ids:
            duplicates.add(identifier)
        ids.add(identifier)
    for identifier in sorted(duplicates):
        issues.append({"severity": "error", "code": "DUPLICATE_ID", "message": identifier})
    for element in root.iter():
        if _local_name(element.tag) not in LINK_TAGS:
            continue
        for role in ("source", "target"):
            endpoint = element.attrib.get(role)
            if not endpoint:
                issues.append({"severity": "error", "code": "MISSING_ENDPOINT", "message": f"{role} on {element.attrib.get('id')}"})
            elif endpoint not in ids:
                issues.append({"severity": "error", "code": "UNKNOWN_ENDPOINT", "message": f"{role}={endpoint}"})
    return issues


def inspect_model(model_path: str) -> dict[str, Any]:
    path, root = parse_xcos(model_path)
    blocks = []
    links = []
    for element in root.iter():
        interface = element.attrib.get("interfaceFunctionName")
        if interface:
            geometry = next((child for child in element if _local_name(child.tag) == "mxGeometry"), None)
            blocks.append({
                "id": element.attrib.get("id"),
                "interface_function": interface,
                "simulation_function": element.attrib.get("simulationFunctionName"),
                "position": None if geometry is None else {
                    "x": float(geometry.attrib.get("x", 0)),
                    "y": float(geometry.attrib.get("y", 0)),
                },
            })
        if _local_name(element.tag) in LINK_TAGS:
            links.append({
                "id": element.attrib.get("id"),
                "kind": _local_name(element.tag),
                "source": element.attrib.get("source"),
                "target": element.attrib.get("target"),
            })
    issues = structural_issues(root)
    return {
        "success": not any(item["severity"] == "error" for item in issues),
        "model_path": str(path),
        "title": root.attrib.get("title", ""),
        "final_integration_time": root.attrib.get("finalIntegrationTime"),
        "recorded_outputs": recorded_outputs(root),
        "blocks": blocks,
        "links": links,
        "issues": issues,
    }


def save_model(xml_content: str, output_path: str, overwrite: bool = False) -> dict[str, object]:
    if not isinstance(xml_content, str) or not xml_content.strip():
        raise ValueError("xml_content must be non-empty")
    encoded = xml_content.encode("utf-8")
    limit = _max_model_bytes()
    if len(encoded) > limit:
        raise ValueError(f"Xcos model exceeds the {limit} byte limit")
    root = ET.fromstring(xml_content)
    if _local_name(root.tag) != "XcosDiagram":
        raise ValueError("XML root must be XcosDiagram")
    issues = structural_issues(root)
    if any(item["severity"] == "error" for item in issues):
        raise ValueError(f"Model has structural errors: {issues}")
    destination = resolve_output_path(output_path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing model: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {"success": True, "model_path": str(destination), "bytes_written": len(payload)}


def validate_model(model_path: str, timeout_seconds: float = 120.0) -> dict[str, object]:
    structure = inspect_model(model_path)
    if not structure["success"]:
        return {**structure, "engine": None, "imported": False}
    path = Path(structure["model_path"])
    with tempfile.TemporaryDirectory(prefix="xcos-mcp-validation-") as directory:
        marker = Path(directory) / "imported.ok"
        script = f'''mode(-1);
lines(0);
loadXcosLibs();
loadScicos();
scs_m = xcosDiagramToScilab(getenv("XCOS_MCP_MODEL_PATH"));
mputl("ok", "{scilab_string(marker)}");
exit(0);
'''
        result = run_scilab_script(
            script,
            timeout_seconds,
            gui=True,
            environment={"XCOS_MCP_MODEL_PATH": str(path)},
        )
        if not wait_for_files([marker]):
            raise RuntimeError(f"Scilab returned without confirming Xcos import: {result.output[-2000:]}")
    return {**structure, "engine": "Scilab/Xcos", "imported": True}
