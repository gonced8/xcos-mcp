# Xcos MCP

Xcos MCP is a generic Model Context Protocol server for controlling a local
Scilab/Xcos installation. It discovers the installed block library, creates
native templates, reads and writes diagrams, validates them with Xcos, runs
simulations for arbitrary positive durations, and returns numerical signals.

```text
MCP client -> xcos-mcp -> Scilab/Xcos -> scicos_simulate -> TOWS_c data
```

The server contains no satellite-specific tools or dynamics. Control examples
and optional space-dynamics examples are ordinary Xcos clients of the same API.

## Requirements

- Python 3.10 or newer
- Scilab with Xcos
- `xvfb-run` on headless Linux systems

The full `scilab` executable is required for Xcos operations. `scilab-cli` is
used only for lightweight runtime checks. Set `SCILAB_GUI_BIN` and
`SCILAB_CLI_BIN` when the executables are not on `PATH`.

## Install and run

```bash
uv sync
uv run xcos-mcp
```

The default transport is stdio. For streamable HTTP:

```bash
XCOS_SERVER_MODE=http XCOS_SERVER_PORT=8000 uv run xcos-mcp
```

Example MCP client configuration:

```json
{
  "command": "/absolute/path/to/xcos-mcp/.venv/bin/python",
  "args": ["-m", "xcos_mcp"],
  "env": {
    "SCILAB_GUI_BIN": "/absolute/path/to/scilab",
    "SCILAB_CLI_BIN": "/absolute/path/to/scilab-cli"
  }
}
```

## Tools

| Tool | Purpose |
| --- | --- |
| `ping` | Check MCP responsiveness. |
| `get_xcos_runtime` | Report Scilab paths, version, and headless support. |
| `list_xcos_blocks` | Discover interfaces from the installed block macros. |
| `get_xcos_block_source` | Read an installed block interface definition. |
| `create_xcos_block_template` | Ask Xcos to export a native one-block diagram. |
| `inspect_xcos_model` | Report blocks, links, duration, and `TOWS_c` outputs. |
| `save_xcos_model` | Structurally check and atomically save Xcos XML. |
| `validate_xcos_model` | Import a diagram using real Scilab/Xcos. |
| `simulate_xcos_model` | Simulate a diagram; return named series inline or persist raw recorder data as an artifact. |
| `read_xcos_simulation_artifact` | Read selected signals and a bounded time window from a persisted simulation artifact. |
| `simulate_first_order_model` | Exercise the real first-order vertical slice. |
| `analyze_step_response` | Calculate standard response and control-effort metrics. |

Numerical extraction currently requires each requested signal to terminate in
a `TOWS_c` block. Use `inspect_xcos_model` to find the configured variable
names, then pass those names to `simulate_xcos_model`.

`simulate_xcos_model` defaults to `result_mode="inline"` for small numerical
jobs. For long, high-rate, or many-signal simulations, set
`result_mode="artifact"`. The server stores raw per-signal CSV files and a
manifest under `.xcos-mcp/artifacts/simulations`, returns compact metadata, and
lets the client retrieve only the signals and time windows it needs with
`read_xcos_simulation_artifact`. This prevents raw time series from needlessly
occupying an LLM tool-response context. Artifact reads are capped at 10,000
numeric values in total, with the effective per-signal sample limit reported
in each response.

## Spacecraft example

The [coupled LEO example](examples/space/coupled_leo/) builds a native Xcos
diagram and then uses this generic MCP server to inspect, validate, and
simulate it for 12,000 seconds. It combines a propagated 3D J2 orbit,
thin-atmosphere drag, eclipse-gated photon pressure, a solar-wind sensitivity,
nonlinear quaternion dynamics, gravity-gradient and centre-of-pressure
torques, and three-axis reaction-wheel control. All 24 telemetry channels
return to the MCP client as numerical series.

```bash
PYTHONPATH=src uv run python examples/space/coupled_leo/run.py
```

## Filesystem policy

Model reads and writes are restricted to the server working directory and the
project root by default. Set `XCOS_ALLOWED_MODEL_ROOTS` to a platform-separated
list of explicit roots. Generated templates and reference-run artifacts go to
`.xcos-mcp/artifacts`, or to `XCOS_ARTIFACT_DIR` when configured.

## Development

```bash
uv run pytest -q -m "not integration"
SCILAB_GUI_BIN=/path/to/scilab uv run pytest -q -m integration
uv build
uv run python scripts/check_wheel.py dist/xcos_mcp-*.whl
```

See [architecture](docs/architecture.md) for component boundaries and
[limitations](docs/limitations.md) for the deliberately deferred engineering
work.

## Licence and provenance

The current source tree is an independent implementation licensed under GNU
GPL version 3 only; see [LICENSE](LICENSE). It does not redistribute Scilab
macros, block catalogues, icons, or reference diagrams. Installed Scilab files
are discovered at runtime.
