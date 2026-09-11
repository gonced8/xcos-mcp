# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

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
