# SPDX-License-Identifier: GPL-3.0-only

import math
from pathlib import Path
import shutil

import pytest

from tests.conftest import FIRST_ORDER_MODEL
from xcos_mcp.catalog import create_block_template, list_blocks
from xcos_mcp.process import resolve_scilab, runtime_info
from xcos_mcp.simulation import simulate_first_order, simulate_model


pytestmark = pytest.mark.integration


def _require_native_xcos() -> None:
    if resolve_scilab(gui=True) is None or shutil.which("xvfb-run") is None:
        pytest.skip("native Scilab/Xcos is unavailable")


def test_installed_runtime_and_block_template():
    _require_native_xcos()
    runtime = runtime_info()
    assert runtime["accessible"] is True
    assert runtime["version"]
    assert any(block["name"] == "CONST_m" for block in list_blocks("CONST_m", 10)["blocks"])
    template = create_block_template("CONST_m", 90)
    assert template["structure"]["success"] is True
    assert template["structure"]["blocks"][0]["interface_function"] == "CONST_m"


def test_real_first_order_then_generic_arbitrary_duration():
    _require_native_xcos()
    reference = simulate_first_order(3.0, 90.0)
    assert reference["metrics"]["value_at_1_second"] == pytest.approx(1 - math.exp(-1), abs=0.01)
    assert all(Path(path).is_file() for path in reference["artifacts"].values())

    result = simulate_model(str(FIRST_ORDER_MODEL), 7.25, ["first_order_y"], 90.0)
    assert result["success"] is True
    assert result["duration_seconds"] == 7.25
    sampled_time = result["time"][-1]
    assert result["signals"]["first_order_y"][-1] == pytest.approx(1 - math.exp(-sampled_time), abs=0.01)
