# Architecture

The implementation has five narrow layers:

1. `server.py` defines the generic MCP contract and transport selection.
2. `config.py` owns artifact locations and the allowed-model-root policy.
3. `process.py` discovers Scilab, bounds subprocesses, captures engine errors,
   and accounts for asynchronous Xcos artifact publication.
4. `catalog.py` and `model.py` discover installed blocks and handle diagram
   inspection, persistence, and native import validation.
5. `simulation.py` drives `scicos_simulate`, reads `TOWS_c` CSV output, limits
   inline response size, persists run-addressed raw-data artifacts when requested,
   and calculates optional response metrics.

The MCP has no copied block database. The installed Scilab tree is the source
of truth, which avoids version drift and redistribution ambiguity. A block
template is also produced by the installed Xcos exporter instead of assembling
undocumented XML from static snippets.

All blocking filesystem and engine operations leave the MCP event loop through
a worker thread. Scilab runs in a separate process group with a caller-provided
timeout. Linux Xcos calls use an isolated virtual display through `xvfb-run`.

The first-order tool is a health check for the complete numerical path, not a
special modelling API. Production diagrams use `simulate_xcos_model`.

For large numerical jobs, `simulate_xcos_model(result_mode="artifact")` copies
raw scalar recorder CSVs to a UUID-addressed artifact directory and writes a
manifest containing schema version, hashes, sizes, sample bounds, and extrema.
`read_xcos_simulation_artifact` uses only the returned run ID, validates it as
an artifact identifier rather than a filesystem path, and returns a bounded
set of signals and samples (at most 10,000 numeric values in total). This
keeps large raw time series out of ordinary MCP responses until a client
explicitly requests a slice.
