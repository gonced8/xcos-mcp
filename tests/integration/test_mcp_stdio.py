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
                assert {"simulate_first_order_model", "simulate_xcos_model"} <= names
                response = await session.call_tool(
                    "simulate_first_order_model",
                    {"duration_seconds": 2.0, "timeout_seconds": 90.0},
                )
                assert response.isError is False
                return json.loads(response.content[0].text)

    payload = asyncio.run(exercise())
    assert payload["engine"] == "Scilab/Xcos"
    assert payload["signals"]["y"][-1] > 0.8
