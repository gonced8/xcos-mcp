# SPDX-License-Identifier: GPL-3.0-only
"""MCP tool surface for controlling a local Scilab/Xcos installation."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .async_utils import run_blocking
from .catalog import block_source, create_block_template, list_blocks
from .model import inspect_model, layout_model, save_model, validate_model
from .process import runtime_info
from .simulation import (
    analyze_step_response as calculate_step_response,
    read_simulation_artifact_async,
    simulate_first_order_async,
    simulate_model_async,
)


SERVER_INSTRUCTIONS = """Control the locally installed Scilab/Xcos runtime.

Inspect installed blocks, create a native block template, save and inspect Xcos
XML, validate a diagram with the real engine, and run simulations that return
numerical TOWS_c signals inline or as persistent artifacts. Paths are
restricted by XCOS_ALLOWED_MODEL_ROOTS.
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
    auto_layout: bool = True,
) -> dict[str, object]:
    """Validate and atomically save Xcos XML, auto-laying out collapsed diagrams by default."""
    return await run_blocking(save_model, xml_content, output_path, overwrite, auto_layout)


@mcp.tool()
async def layout_xcos_model(
    model_path: str,
    output_path: str,
    overwrite: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Create a readable left-to-right layout for a saved Xcos diagram without changing its equations."""
    return await run_blocking(layout_model, model_path, output_path, overwrite, force)


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
    result_mode: str = "inline",
) -> dict[str, Any]:
    """Run a real diagram and return inline TOWS_c data or a compact persisted artifact manifest."""
    return await simulate_model_async(
        model_path,
        duration_seconds,
        outputs,
        timeout_seconds,
        max_samples,
        result_mode,
    )


@mcp.tool()
async def read_xcos_simulation_artifact(
    run_id: str,
    outputs: list[str],
    start_time_seconds: float | None = None,
    end_time_seconds: float | None = None,
    max_samples: int = 1_000,
) -> dict[str, Any]:
    """Return only selected TOWS_c signals and a bounded time window from a saved simulation artifact."""
    return await read_simulation_artifact_async(
        run_id,
        outputs,
        start_time_seconds,
        end_time_seconds,
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
