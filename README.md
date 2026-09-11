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
| `simulate_xcos_model` | Simulate a diagram and return named numerical series. |
| `simulate_first_order_model` | Exercise the real first-order vertical slice. |
| `analyze_step_response` | Calculate standard response and control-effort metrics. |

Numerical extraction currently requires each requested signal to terminate in
a `TOWS_c` block. Use `inspect_xcos_model` to find the configured variable
names, then pass those names to `simulate_xcos_model`.

## Spacecraft example

The [three-axis spacecraft example](examples/space/README.md) builds a native
Xcos diagram and then uses this MCP server to inspect, validate, and simulate
it for 12,000 seconds. The checked-in run includes attitude, body-rate,
reaction-wheel torque, and environmental-disturbance histories for all axes.

```bash
PYTHONPATH=src uv run python examples/space/run_realistic_satellite.py
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
