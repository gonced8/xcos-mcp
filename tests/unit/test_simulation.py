# SPDX-License-Identifier: GPL-3.0-only

import math
from pathlib import Path

import pytest

from tests.conftest import FIRST_ORDER_MODEL
from xcos_mcp.simulation import (
    _persist_simulation_artifact,
    _signal_names,
    _validate_max_samples,
    _validate_result_mode,
    analyze_step_response,
    read_simulation_artifact,
    simulate_model,
)


def test_unknown_output_is_rejected_before_engine_launch():
    with pytest.raises(ValueError, match="available:.*first_order_y"):
        simulate_model(str(FIRST_ORDER_MODEL), 1.0, ["not_recorded"])


@pytest.mark.parametrize("duration", [0, -1, math.inf, math.nan])
def test_duration_must_be_positive_and_finite(duration: float):
    with pytest.raises(ValueError, match="positive finite"):
        simulate_model(str(FIRST_ORDER_MODEL), duration, ["first_order_y"])


def test_step_metrics_cover_output_and_control_effort():
    metrics = analyze_step_response(
        [0, 1, 2, 3],
        [0, 0.7, 0.95, 1.0],
        1.0,
        control=[2, 1, 0.5, 0],
        saturation_limit=2,
    )
    assert metrics["rise_time"] == 1
    assert metrics["settling_time"] == 3
    assert metrics["maximum_absolute_control_input"] == 2
    assert metrics["time_in_saturation"] == 1


@pytest.mark.parametrize("maximum", [1, 100_001, True, 2.5])
def test_response_size_is_bounded_before_engine_launch(maximum):
    with pytest.raises(ValueError, match="max_samples"):
        _validate_max_samples(maximum)


def test_output_count_is_bounded():
    with pytest.raises(ValueError, match="more than"):
        _signal_names([f"y{index}" for index in range(65)])


def test_result_mode_is_explicit_and_backward_compatible():
    assert _validate_result_mode("inline") == "inline"
    assert _validate_result_mode("artifact") == "artifact"
    with pytest.raises(ValueError, match="result_mode"):
        _validate_result_mode("everything")


def test_artifact_reader_returns_only_requested_window(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    sources = {}
    for name, values in {"altitude": [500.0, 501.0, 502.0, 503.0], "rate": [0.0, 1.0, 2.0, 3.0]}.items():
        source = tmp_path / f"{name}.csv"
        source.write_text("".join(f"{time},{value}\n" for time, value in enumerate(values)), encoding="utf-8")
        sources[name] = source

    artifact, counts = _persist_simulation_artifact(
        sources,
        model_path=FIRST_ORDER_MODEL,
        duration_seconds=3.0,
        available_outputs=["altitude", "rate"],
    )
    result = read_simulation_artifact(
        artifact["run_id"],
        ["altitude"],
        start_time_seconds=0.5,
        end_time_seconds=2.5,
    )

    assert counts == {"altitude": 4, "rate": 4}
    assert result["signals"] == {"altitude": [501.0, 502.0]}
    assert result["time"] == [1.0, 2.0]
    assert result["original_sample_counts"] == {"altitude": 2}
    assert Path(artifact["manifest_path"]).is_file()


def test_artifact_reader_rejects_unknown_signal(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    source = tmp_path / "y.csv"
    source.write_text("0,1\n1,2\n", encoding="utf-8")
    artifact, _ = _persist_simulation_artifact(
        {"y": source},
        model_path=FIRST_ORDER_MODEL,
        duration_seconds=1.0,
        available_outputs=["y"],
    )
    with pytest.raises(ValueError, match="available"):
        read_simulation_artifact(artifact["run_id"], ["missing"])
