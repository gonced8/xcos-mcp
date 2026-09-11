# SPDX-License-Identifier: GPL-3.0-only

import math

import pytest

from tests.conftest import FIRST_ORDER_MODEL
from xcos_mcp.simulation import _signal_names, _validate_max_samples, analyze_step_response, simulate_model


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
