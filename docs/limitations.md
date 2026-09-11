# Current limitations

- Signals must already be connected to `TOWS_c`; automatic wire
  instrumentation is not implemented.
- Diagram editing is XML-level. The server can create native single-block
  templates, but does not yet offer typed add/connect/configure operations.
- Automatic layout is a conservative top-level signal-lane pass. It improves
  collapsed generated diagrams, but does not yet optimize all feedback routes,
  nested superblocks, annotations, or semantic subsystem grouping.
- Native semantic validation currently confirms that Xcos imports the model;
  compile-only diagnostics are not normalized into structured issue codes.
- Scilab's graphical runtime is required for Xcos import/export and simulation,
  including on headless systems.
- Long simulations are bounded by a subprocess timeout. Inline responses are
  downsampled and artifact mode avoids returning raw arrays, but there is no
  asynchronous job API, retention policy, storage quota, or progress reporting.
- Multi-column, complex, and event-valued recorder outputs need richer result
  schemas; the current CSV reader returns one scalar value column per recorder.
- The HTTP transport has no built-in authentication or multi-tenant isolation.

The highest-value next slice is typed, schema-aware diagram construction:
create blocks from native templates, configure expressions, connect validated
ports, save, compile, simulate, and return recorder data without exposing raw
XML to the client.
