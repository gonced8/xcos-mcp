# SPDX-License-Identifier: GPL-3.0-only
"""MCP tool surface for controlling a local Scilab/Xcos installation."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .async_utils import run_blocking
from .catalog import block_source, create_block_template, list_blocks
from .model import inspect_model, save_model, validate_model
from .process import runtime_info
from .simulation import (
    analyze_step_response as calculate_step_response,
    simulate_first_order_async,
    simulate_model_async,
)


SERVER_INSTRUCTIONS = """Control the locally installed Scilab/Xcos runtime.

Inspect installed blocks, create a native block template, save and inspect Xcos
XML, validate a diagram with the real engine, and run simulations that return
numerical TOWS_c signals. Paths are restricted by XCOS_ALLOWED_MODEL_ROOTS.
"""


mcp = FastMCP(
    "Xcos MCP",
    instructions=SERVER_INSTRUCTIONS,
    host=os.environ.get("XCOS_SERVER_HOST", "127.0.0.1"),
    port=int(os.environ.get("XCOS_SERVER_PORT", "8000")),
    stateless_http=True,
)


@mcp.tool()
def ping() -> dict[str, object]:
    """Check that the MCP process is responsive."""
    return {"success": True, "server": "xcos-mcp"}


@mcp.tool()
async def get_xcos_runtime() -> dict[str, object]:
    """Report the discovered Scilab CLI, Xcos-capable GUI, and exact version."""
    return await run_blocking(runtime_info)


@mcp.tool()
async def list_xcos_blocks(query: str = "", limit: int = 100) -> dict[str, object]:
    """List block interfaces discovered from the installed Xcos macros."""
    return await run_blocking(list_blocks, query, limit)


@mcp.tool()
async def get_xcos_block_source(name: str) -> dict[str, object]:
    """Read an installed block's Scilab interface source for accurate configuration."""
    return await run_blocking(block_source, name)


@mcp.tool()
async def create_xcos_block_template(
    name: str,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """Ask real Xcos to export a one-block diagram and return its XML."""
    return await run_blocking(create_block_template, name, timeout_seconds)


@mcp.tool()
async def inspect_xcos_model(model_path: str) -> dict[str, Any]:
    """Inspect a saved Xcos diagram, including blocks, links, and recorded outputs."""
    return await run_blocking(inspect_model, model_path)


@mcp.tool()
async def save_xcos_model(
    xml_content: str,
    output_path: str,
    overwrite: bool = False,
) -> dict[str, object]:
    """Validate basic structure and atomically save Xcos XML inside an allowed root."""
    return await run_blocking(save_model, xml_content, output_path, overwrite)


@mcp.tool()
async def validate_xcos_model(
    model_path: str,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """Perform structural checks and import the diagram with real Scilab/Xcos."""
    return await run_blocking(validate_model, model_path, timeout_seconds)


@mcp.tool()
async def simulate_xcos_model(
    model_path: str,
    duration_seconds: float,
    outputs: list[str],
    timeout_seconds: float = 120.0,
    max_samples: int = 10_000,
) -> dict[str, Any]:
    """Run a real diagram for any positive duration and return requested TOWS_c series."""
    return await simulate_model_async(
        model_path,
        duration_seconds,
        outputs,
        timeout_seconds,
        max_samples,
    )


@mcp.tool()
async def simulate_first_order_model(
    duration_seconds: float = 10.0,
    timeout_seconds: float = 120.0,
    max_samples: int = 10_000,
) -> dict[str, Any]:
    """Build and simulate G(s)=1/(s+1) in real Xcos, returning its numerical response."""
    return await simulate_first_order_async(duration_seconds, timeout_seconds, max_samples)


@mcp.tool()
def analyze_step_response(
    time: list[float],
    signal: list[float],
    reference: float,
    control: list[float] | None = None,
    saturation_limit: float | None = None,
) -> dict[str, float | None]:
    """Calculate rise, settling, overshoot, error, and optional control-effort metrics."""
    return calculate_step_response(time, signal, reference, control, saturation_limit)


def main() -> None:
    """Run over stdio by default, or streamable HTTP when configured."""
    requested = os.environ.get("XCOS_SERVER_MODE", "stdio").strip().lower()
    transport = "streamable-http" if requested in {"http", "streamable-http"} else requested
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("XCOS_SERVER_MODE must be stdio, sse, http, or streamable-http")
    mcp.run(transport=transport)
