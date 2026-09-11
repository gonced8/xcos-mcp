# SPDX-License-Identifier: GPL-3.0-only

import asyncio
import os
from pathlib import Path

from tests.conftest import FIRST_ORDER_MODEL
from xcos_mcp.model import layout_model
from xcos_mcp.server import mcp


def test_generic_tool_surface_is_small_and_explicit():
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {
        "ping",
        "get_xcos_runtime",
        "list_xcos_blocks",
        "get_xcos_block_source",
        "create_xcos_block_template",
        "inspect_xcos_model",
        "save_xcos_model",
        "layout_xcos_model",
        "validate_xcos_model",
        "simulate_xcos_model",
        "read_xcos_simulation_artifact",
        "simulate_first_order_model",
        "analyze_step_response",
    }


def test_layout_implementation_preserves_equations_while_creating_a_new_diagram(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XCOS_ALLOWED_MODEL_ROOTS", os.pathsep.join((str(tmp_path), str(FIRST_ORDER_MODEL.parent))))
    destination = tmp_path / "reflowed.xcos"
    result = layout_model(str(FIRST_ORDER_MODEL), str(destination), force=True)

    assert result["success"] is True
    assert result["layout"]["applied"] is True
    assert destination.is_file()
