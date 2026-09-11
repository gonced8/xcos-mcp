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
LAYOUT_HORIZONTAL_SPACING = 80.0
LAYOUT_VERTICAL_SPACING = 65.0
LAYOUT_MARGIN = 40.0
LAYOUT_MAIN_LANE_Y = 180.0
LAYOUT_SIDE_LANE_Y = 300.0
LAYOUT_RECORDER_LANE_Y = 60.0
LAYOUT_CLOCK_LANE_Y = 10.0


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


def _top_level_graph_objects(root: ET.Element) -> tuple[list[ET.Element], list[ET.Element]]:
    """Return executable top-level blocks and links, excluding nested superblocks."""
    graph = next((element for element in root.iter() if _local_name(element.tag) == "root"), None)
    if graph is None:
        return [], []
    blocks = [element for element in graph if element.attrib.get("interfaceFunctionName")]
    links = [element for element in graph if _local_name(element.tag) in LINK_TAGS]
    return blocks, links


def _block_geometry(block: ET.Element) -> ET.Element:
    geometry = next((child for child in block if _local_name(child.tag) == "mxGeometry"), None)
    if geometry is None:
        geometry = ET.SubElement(block, "mxGeometry", {"as": "geometry"})
    return geometry


def _geometry_position(block: ET.Element) -> tuple[float, float]:
    geometry = _block_geometry(block)
    return float(geometry.attrib.get("x", 0)), float(geometry.attrib.get("y", 0))


def _set_link_points(link: ET.Element, points: list[tuple[float, float]]) -> None:
    """Replace an Xcos link's manual routing points.

    Xcos uses the mxGraph ``Array as=\"points\"`` representation.  Supplying
    two points gives the editor a stable, orthogonal-looking lane instead of a
    long diagonal chosen from collapsed source geometry.
    """
    geometry = next((child for child in link if _local_name(child.tag) == "mxGeometry"), None)
    if geometry is None:
        geometry = ET.SubElement(link, "mxGeometry", {"as": "geometry"})
    for child in list(geometry):
        if child.attrib.get("as") == "points":
            geometry.remove(child)
    array = ET.SubElement(geometry, "Array", {"as": "points"})
    for x, y in points:
        ET.SubElement(array, "mxPoint", {"x": f"{x:g}", "y": f"{y:g}"})


def _layout_root(root: ET.Element, *, force: bool = False) -> dict[str, object]:
    """Lay out a top-level Xcos signal graph with explicit signal lanes.

    The executable path runs left to right.  Feedback and disturbance branches
    use lower lanes with explicit mxGraph waypoints; recorder and clock pairs
    sit below the model.  This is deliberately topology based rather than tied
    to a particular engineering domain.
    """
    blocks, links = _top_level_graph_objects(root)
    if not blocks:
        return {"applied": False, "reason": "no_top_level_blocks", "blocks_repositioned": 0}
    positions = {_geometry_position(block) for block in blocks}
    if not force and len(positions) > 1:
        return {"applied": False, "reason": "existing_layout_preserved", "blocks_repositioned": 0}

    by_id = {block.attrib.get("id"): block for block in blocks if block.attrib.get("id")}
    port_parent: dict[str, str] = {}
    port_order: dict[str, int] = {}
    for port in root.iter():
        port_id = port.attrib.get("id")
        parent_id = port.attrib.get("parent")
        if port_id and parent_id in by_id:
            port_parent[port_id] = parent_id
            port_order[port_id] = int(port.attrib.get("ordering", "1"))

    document_order = {identifier: index for index, identifier in enumerate(by_id)}
    connections: list[dict[str, object]] = []
    for link in links:
        source = port_parent.get(link.attrib.get("source", ""))
        target = port_parent.get(link.attrib.get("target", ""))
        if not source or not target or source == target:
            continue
        connections.append({
            "link": link,
            "kind": _local_name(link.tag),
            "source": source,
            "target": target,
            "target_order": port_order.get(link.attrib.get("target", ""), 1),
        })

    feedback_connections = [
        connection for connection in connections
        if connection["kind"] == "ExplicitLink"
        and by_id[str(connection["target"])].attrib.get("interfaceFunctionName") == "SUMMATION"
        and int(connection["target_order"]) > 1
    ]
    feedback_links = {id(connection["link"]) for connection in feedback_connections}
    feedback_sources = {str(connection["source"]) for connection in feedback_connections}
    ordinary_outgoing = {
        source for source in by_id
        if any(
            connection["kind"] == "ExplicitLink"
            and connection["source"] == source
            and id(connection["link"]) not in feedback_links
            for connection in connections
        )
    }
    # A source used only as a secondary summation input is a disturbance or a
    # feedback-conditioning branch.  Keep it outside the main signal lane.
    side_blocks = feedback_sources - ordinary_outgoing

    edges: list[tuple[str, str]] = []
    for connection in connections:
        if connection["kind"] != "ExplicitLink" or id(connection["link"]) in feedback_links:
            continue
        source = str(connection["source"])
        target = str(connection["target"])
        if by_id[target].attrib.get("interfaceFunctionName") == "TOWS_c":
            continue
        target_block = by_id[target]
        # Most generated models serialize the forward path in block order.
        # Ignore ordinary reverse links as feedback; the actual feedback link
        # is routed below the main lane.
        if (
            by_id[source].attrib.get("interfaceFunctionName") != "SPLIT_f"
            and document_order[source] > document_order[target]
        ):
            continue
        edges.append((source, target))

    ranks = {identifier: 0 for identifier in by_id}
    for _ in range(len(by_id)):
        changed = False
        for source, target in edges:
            candidate = ranks[source] + 1
            if candidate > ranks[target]:
                ranks[target] = candidate
                changed = True
        if not changed:
            break

    columns: dict[int, list[ET.Element]] = {}
    for block in blocks:
        identifier = block.attrib.get("id")
        if identifier and identifier not in side_blocks and block.attrib.get("interfaceFunctionName") not in {"TOWS_c", "CLOCK_c"}:
            columns.setdefault(ranks[identifier], []).append(block)
    for rank, column in columns.items():
        column.sort(key=lambda block: block.attrib.get("id", ""))
        for row, block in enumerate(column):
            geometry = _block_geometry(block)
            geometry.attrib["x"] = f"{LAYOUT_MARGIN + rank * LAYOUT_HORIZONTAL_SPACING:g}"
            lane_y = LAYOUT_MAIN_LANE_Y + row * LAYOUT_VERTICAL_SPACING
            # SPLIT_f is a graphical junction rather than a full-sized block.
            # Give it the small offset used by native Xcos examples so the
            # junction lies on the signal line instead of below the diagram.
            if block.attrib.get("interfaceFunctionName") == "SPLIT_f":
                lane_y += 16.0
            geometry.attrib["y"] = f"{lane_y:g}"

    # Place secondary-input-only branches near the summation they feed, but in
    # their own lower lane.  This is the familiar control-diagram convention.
    for index, source in enumerate(sorted(side_blocks)):
        target = next(str(item["target"]) for item in feedback_connections if item["source"] == source)
        target_x, _ = _geometry_position(by_id[target])
        geometry = _block_geometry(by_id[source])
        direction = -1 if by_id[source].attrib.get("interfaceFunctionName") == "CONST_m" else 1
        geometry.attrib["x"] = f"{target_x + direction * LAYOUT_HORIZONTAL_SPACING * 1.35:g}"
        geometry.attrib["y"] = f"{LAYOUT_SIDE_LANE_Y + index * LAYOUT_VERTICAL_SPACING:g}"

    # Recorder signals are vertically aligned with their measured source; the
    # associated CLOCK_c goes directly beneath it.  This keeps telemetry out
    # of the plant/controller signal path and avoids event-wire diagonals.
    recorder_sources: dict[str, str] = {}
    for connection in connections:
        if (
            connection["kind"] == "ExplicitLink"
            and by_id[str(connection["target"])].attrib.get("interfaceFunctionName") == "TOWS_c"
        ):
            recorder_sources[str(connection["target"])] = str(connection["source"])
    recorder_blocks = [block for block in blocks if block.attrib.get("interfaceFunctionName") == "TOWS_c"]
    occupied_recorder_x: set[float] = set()
    for row, recorder in enumerate(sorted(recorder_blocks, key=lambda block: block.attrib.get("id", ""))):
        recorder_id = recorder.attrib.get("id", "")
        source_x, _ = _geometry_position(by_id[recorder_sources[recorder_id]])
        while source_x in occupied_recorder_x:
            source_x += LAYOUT_HORIZONTAL_SPACING * 0.45
        occupied_recorder_x.add(source_x)
        geometry = _block_geometry(recorder)
        geometry.attrib["x"] = f"{source_x:g}"
        geometry.attrib["y"] = f"{LAYOUT_RECORDER_LANE_Y:g}"
        for connection in connections:
            if connection["target"] != recorder_id or connection["kind"] != "CommandControlLink":
                continue
            clock = by_id[str(connection["source"])]
            clock_geometry = _block_geometry(clock)
            clock_geometry.attrib["x"] = f"{source_x:g}"
            clock_geometry.attrib["y"] = f"{LAYOUT_CLOCK_LANE_Y:g}"

    # Route only feedbacks into progressively lower lanes.  Xcos itself is the
    # authority on ordinary connection geometry (especially around SPLIT_f and
    # recorder ports); persisting guessed bend points for those links creates
    # the very visual tangles this formatter is intended to prevent.
    feedback_order = sorted(
        feedback_connections,
        key=lambda item: abs(_geometry_position(by_id[str(item["source"])])[0] - _geometry_position(by_id[str(item["target"])])[0]),
    )
    feedback_lanes = {id(item["link"]): LAYOUT_SIDE_LANE_Y + 60.0 + index * 95.0 for index, item in enumerate(feedback_order)}
    for connection in connections:
        link = connection["link"]
        source_x, source_y = _geometry_position(by_id[str(connection["source"])])
        target_x, target_y = _geometry_position(by_id[str(connection["target"])])
        if id(link) in feedback_lanes:
            lane_y = feedback_lanes[id(link)]
            _set_link_points(link, [(source_x + 32.0, lane_y), (target_x - 18.0, lane_y)])
        else:
            _set_link_points(link, [])
    return {
        "applied": True,
        "reason": "forced" if force else "collapsed_geometry",
        "blocks_repositioned": len(blocks),
        "columns": len(columns),
        "routed_links": len(connections),
    }


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


def _write_model(root: ET.Element, destination: Path, overwrite: bool) -> dict[str, object]:
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


def save_model(
    xml_content: str,
    output_path: str,
    overwrite: bool = False,
    auto_layout: bool = True,
) -> dict[str, object]:
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
    if not isinstance(auto_layout, bool):
        raise ValueError("auto_layout must be a boolean")
    destination = resolve_output_path(output_path)
    layout = _layout_root(root) if auto_layout else {"applied": False, "reason": "disabled", "blocks_repositioned": 0}
    return {**_write_model(root, destination, overwrite), "layout": layout}


def layout_model(
    model_path: str,
    output_path: str,
    overwrite: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Persist a readable left-to-right layout for a saved Xcos diagram."""
    if not isinstance(force, bool):
        raise ValueError("force must be a boolean")
    _, root = parse_xcos(model_path)
    issues = structural_issues(root)
    if any(item["severity"] == "error" for item in issues):
        raise ValueError(f"Model has structural errors: {issues}")
    destination = resolve_output_path(output_path)
    layout = _layout_root(root, force=force)
    return {**_write_model(root, destination, overwrite), "layout": layout}


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
