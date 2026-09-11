# SPDX-License-Identifier: GPL-3.0-only
"""Regression checks for the checked-in real-Xcos coupled LEO run."""

import csv
import json
import math

import pytest

from tests.conftest import PROJECT_ROOT


def test_checked_in_coupled_leo_result_is_physical_and_came_through_mcp():
    path = PROJECT_ROOT / "examples" / "space" / "coupled_leo" / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    metrics = summary["metrics"]

    assert summary["engine"] == "Scilab/Xcos"
    assert summary["model_imported"] is True
    assert summary["mcp_tools_used"] == [
        "inspect_xcos_model",
        "validate_xcos_model",
        "simulate_xcos_model",
    ]
    assert summary["duration_seconds"] == 12_000.0
    assert summary["returned_samples"] == 1_200
    assert metrics["minimum_altitude_km"] > 450.0
    assert metrics["maximum_altitude_km"] < 550.0
    assert metrics["eclipse_fraction"] > 0.1
    assert metrics["maximum_density_kg_m3"] > 0.0
    assert metrics["peak_environmental_torque_Nm"] > 1e-6
    assert metrics["maximum_quaternion_norm_error"] < 1e-5
    assert metrics["final_attitude_error_deg"] < 0.1
    assert metrics["observed_raan_change_deg"] == pytest.approx(
        metrics["first_order_J2_raan_change_deg"], abs=0.05
    )


def test_checked_in_coupled_leo_telemetry_is_aligned_and_numerical():
    path = PROJECT_ROOT / "examples" / "space" / "coupled_leo" / "coupled_leo.csv"
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    assert len(rows) == 1_200
    assert rows[0].keys() == {
        "time_s", "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps",
        "altitude_km", "speed_mps", "density_kgm3", "sunlight", "q_norm",
        "q0", "q1", "q2", "q3", "wx_rads", "wy_rads", "wz_rads",
        "control_x_Nm", "control_y_Nm", "control_z_Nm",
        "disturbance_x_Nm", "disturbance_y_Nm", "disturbance_z_Nm",
    }
    assert all(math.isfinite(float(value)) for row in rows for value in row.values())
    assert float(rows[0]["time_s"]) == 0.0
    assert float(rows[-1]["time_s"]) == 11_990.0
