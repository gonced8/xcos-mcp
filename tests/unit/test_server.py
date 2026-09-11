# SPDX-License-Identifier: GPL-3.0-only

import asyncio

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
        "validate_xcos_model",
        "simulate_xcos_model",
        "read_xcos_simulation_artifact",
        "simulate_first_order_model",
        "analyze_step_response",
    }
