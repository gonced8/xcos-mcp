# SPDX-License-Identifier: GPL-3.0-only

import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from xcos_mcp.process import resolve_scilab


pytestmark = pytest.mark.integration


def test_stdio_mcp_reaches_real_xcos_and_returns_numbers():
    if resolve_scilab(gui=True) is None or shutil.which("xvfb-run") is None:
        pytest.skip("native Scilab/Xcos is unavailable")

    async def exercise() -> dict:
        parameters = StdioServerParameters(
            command=str(Path(".venv/bin/python").absolute()),
            args=["-m", "xcos_mcp"],
            env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        )
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "simulate_first_order_model",
                    "simulate_xcos_model",
                    "read_xcos_simulation_artifact",
                } <= names
                response = await session.call_tool(
                    "simulate_first_order_model",
                    {"duration_seconds": 2.0, "timeout_seconds": 90.0},
                )
                assert response.isError is False
                inline = json.loads(response.content[0].text)
                artifact_response = await session.call_tool(
                    "simulate_xcos_model",
                    {
                        "model_path": str(Path("examples/control/first_order.xcos").resolve()),
                        "duration_seconds": 2.0,
                        "outputs": ["first_order_y"],
                        "timeout_seconds": 90.0,
                        "result_mode": "artifact",
                    },
                )
                assert artifact_response.isError is False
                artifact = json.loads(artifact_response.content[0].text)
                assert "signals" not in artifact
                slice_response = await session.call_tool(
                    "read_xcos_simulation_artifact",
                    {
                        "run_id": artifact["artifact"]["run_id"],
                        "outputs": ["first_order_y"],
                        "max_samples": 100,
                    },
                )
                assert slice_response.isError is False
                return {"inline": inline, "slice": json.loads(slice_response.content[0].text)}

    payload = asyncio.run(exercise())
    assert payload["inline"]["engine"] == "Scilab/Xcos"
    assert payload["inline"]["signals"]["y"][-1] > 0.8
    assert payload["slice"]["signals"]["first_order_y"][-1] > 0.8
