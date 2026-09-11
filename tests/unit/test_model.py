# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.conftest import COUPLED_LEO_MODEL, FIRST_ORDER_MODEL
from xcos_mcp.model import inspect_model, save_model


def test_inspection_finds_native_recorders():
    report = inspect_model(str(FIRST_ORDER_MODEL))
    assert report["success"] is True
    assert report["recorded_outputs"] == ["first_order_y"]
    assert "TOWS_c" in {block["interface_function"] for block in report["blocks"]}


def test_coupled_leo_model_has_orbit_attitude_and_force_telemetry():
    report = inspect_model(str(COUPLED_LEO_MODEL))
    expected = {
        "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps",
        "altitude_km", "speed_mps", "density_kgm3", "sunlight", "q_norm",
        "q0", "q1", "q2", "q3", "wx_rads", "wy_rads", "wz_rads",
        "control_x_Nm", "control_y_Nm", "control_z_Nm",
        "disturbance_x_Nm", "disturbance_y_Nm", "disturbance_z_Nm",
    }
    assert report["success"] is True
    assert set(report["recorded_outputs"]) == expected
    assert len(report["blocks"]) == 291
    assert len(report["links"]) == 442


def test_save_is_atomic_and_refuses_implicit_overwrite(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    destination = tmp_path / "diagram.xcos"
    xml = '<XcosDiagram title="empty" finalIntegrationTime="1"/>'
    result = save_model(xml, str(destination))
    assert result["bytes_written"] > 0
    assert destination.is_file()
    with pytest.raises(FileExistsError):
        save_model(xml, str(destination))


def test_save_auto_layout_separates_collapsed_top_level_blocks(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    destination = tmp_path / "laid_out.xcos"
    xml = """<XcosDiagram><mxGraphModel><root>
      <BasicBlock id="source" interfaceFunctionName="CONST_m"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <BasicBlock id="target" interfaceFunctionName="GAINBLK"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
    </root></mxGraphModel></XcosDiagram>"""
    result = save_model(xml, str(destination))
    root = ET.parse(destination).getroot()
    positions = {
        block.attrib["id"]: (geometry.attrib["x"], geometry.attrib["y"])
        for block in root.iter("BasicBlock")
        for geometry in block.iter("mxGeometry")
    }

    assert result["layout"]["applied"] is True
    assert result["layout"]["blocks_repositioned"] == 2
    assert len(set(positions.values())) == 2


def test_auto_layout_uses_signal_links_for_left_to_right_columns(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    destination = tmp_path / "signal_flow.xcos"
    xml = """<XcosDiagram><mxGraphModel><root>
      <BasicBlock id="source" interfaceFunctionName="CONST_m"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitOutputPort id="source_out" parent="source" ordering="1"/>
      <BasicBlock id="target" interfaceFunctionName="GAINBLK"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitInputPort id="target_in" parent="target" ordering="1"/>
      <ExplicitLink id="flow" source="source_out" target="target_in"/>
    </root></mxGraphModel></XcosDiagram>"""
    result = save_model(xml, str(destination))
    report = inspect_model(str(destination))
    positions = {block["id"]: block["position"]["x"] for block in report["blocks"]}

    assert result["layout"]["columns"] == 2
    assert positions["source"] < positions["target"]


def test_auto_layout_routes_feedback_and_separates_recorder_clock_pairs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    destination = tmp_path / "closed_loop.xcos"
    xml = """<XcosDiagram><mxGraphModel><root>
      <BasicBlock id="reference" interfaceFunctionName="CONST_m"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitOutputPort id="reference_out" parent="reference" ordering="1"/>
      <BasicBlock id="sum" interfaceFunctionName="SUMMATION"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitInputPort id="sum_ref" parent="sum" ordering="1"/><ExplicitInputPort id="sum_feedback" parent="sum" ordering="2"/>
      <BasicBlock id="plant" interfaceFunctionName="GAINBLK"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitInputPort id="plant_in" parent="plant" ordering="1"/><ExplicitOutputPort id="plant_out" parent="plant" ordering="1"/>
      <BasicBlock id="recorder" interfaceFunctionName="TOWS_c"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <ExplicitInputPort id="recorder_in" parent="recorder" ordering="1"/><ControlPort id="recorder_event" parent="recorder" ordering="1"/>
      <BasicBlock id="clock" interfaceFunctionName="CLOCK_c"><mxGeometry as="geometry" x="0" y="0"/></BasicBlock>
      <CommandPort id="clock_out" parent="clock" ordering="1"/>
      <ExplicitLink id="reference_flow" source="reference_out" target="sum_ref"/>
      <ExplicitLink id="plant_flow" source="plant_out" target="sum_feedback"/>
      <ExplicitLink id="measurement" source="plant_out" target="recorder_in"/>
      <CommandControlLink id="sampling" source="clock_out" target="recorder_event"/>
    </root></mxGraphModel></XcosDiagram>"""
    save_model(xml, str(destination))
    root = ET.parse(destination).getroot()
    blocks = {block.attrib["id"]: block for block in root.iter("BasicBlock")}
    geometry = lambda identifier: next(blocks[identifier].iter("mxGeometry"))
    feedback = next(link for link in root.iter("ExplicitLink") if link.attrib["id"] == "plant_flow")
    points = next(child for child in feedback.iter("Array") if child.attrib.get("as") == "points")

    assert float(geometry("recorder").attrib["y"]) < float(geometry("plant").attrib["y"])
    assert float(geometry("recorder").attrib["x"]) == float(geometry("plant").attrib["x"])
    assert float(geometry("clock").attrib["y"]) < float(geometry("recorder").attrib["y"])
    assert len(list(points)) == 2


def test_allowed_roots_block_read_and_write(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="outside"):
        inspect_model(str(FIRST_ORDER_MODEL))
    with pytest.raises(ValueError, match="outside"):
        save_model("<XcosDiagram/>", str(tmp_path.parent / "escape.xcos"))


def test_structural_errors_prevent_save(tmp_path: Path):
    xml = '<XcosDiagram><ExplicitLink id="link" source="missing"/></XcosDiagram>'
    with pytest.raises(ValueError, match="structural errors"):
        save_model(xml, str(tmp_path / "broken.xcos"))


def test_model_size_is_bounded_before_parsing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", str(tmp_path))
    monkeypatch.setenv("XCOS_MAX_MODEL_BYTES", "10")
    with pytest.raises(ValueError, match="byte limit"):
        save_model("<XcosDiagram/>", str(tmp_path / "large.xcos"))
