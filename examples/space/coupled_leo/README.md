# Coupled low-Earth-orbit simulation

This is an end-to-end engineering example for the generic Xcos MCP: it builds
a native `.xcos` diagram, validates it in real Scilab/Xcos, simulates it, and
returns numerical telemetry through MCP. The server has no spacecraft-specific
tools or assumptions; all space-dynamics logic lives in this example.

```text
Python runner -> MCP stdio client -> xcos-mcp -> Scilab/Xcos -> numerical TOWS_c signals
```

The checked-in diagram has 16 continuous states, 291 blocks, 442 links, and
24 `TOWS_c` recorders.

## Quick start

From the repository root, install the locked Python environment and run:

```bash
uv sync
uv run python examples/space/coupled_leo/run.py
```

The run requires a local Scilab installation with Xcos. On headless Linux it
also requires `xvfb-run`. Set `SCILAB_GUI_BIN` and `SCILAB_CLI_BIN` when the
Scilab executables are not on `PATH`.

The runner generates the diagram to a temporary location and only replaces
`coupled_leo.xcos` after Xcos has exported a stable file. It then calls these
generic MCP tools in sequence:

1. `inspect_xcos_model`
2. `validate_xcos_model`
3. `simulate_xcos_model`

The reference run lasts 12,000 seconds. It normally returns 1,200 samples at
10-second intervals, from `t = 0` through `t = 11,990 s`.

## What the model represents

The initial condition is a 480 x 520 km, 51.6-degree inclined orbit. All
quantities use SI units unless a telemetry name says otherwise.

| Subsystem | Included behaviour |
| --- | --- |
| Translational dynamics | Three-dimensional Earth-centred inertial propagation with central gravity and J2 oblateness. |
| Atmosphere and drag | Co-rotating exponential thermosphere, velocity-relative drag, and an aerodynamic centre-of-pressure torque. |
| Sun and solar wind | Fixed Sun direction, cylindrical Earth eclipse, eclipse-gated photon pressure, and a deliberately small direct solar-wind-pressure sensitivity. |
| Attitude | Four-element quaternion kinematics, full Euler rigid-body coupling, and instantaneous gravity-gradient torque. |
| Actuation and control | Three independently saturated reaction-wheel torque channels with 0.15 s first-order response and quaternion feedback for inertial pointing. |

The Earth/J2 constants, gravity-gradient expression, drag form, and nominal
solar-radiation pressure are based on public engineering references: the
[NASA GEONS mathematical specification](https://ntrs.nasa.gov/api/citations/20240004259/downloads/GEONSMS_R3_0_NASA-TP-20240004259.pdf),
[NASA gravity-gradient derivation](https://ntrs.nasa.gov/api/citations/19740022191/downloads/19740022191.pdf),
[NASA/PDS drag model](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=MPFL-M-ASIMET-4-DDR-EDL-V1.0),
and NASA's [solar-radiation-pressure value](https://www.grc.nasa.gov/WWW/k-12/Numbers/Math/Mathematical_Thinking/sunlight_exerts_pressure.htm).

## Telemetry returned through MCP

Every channel below is a real Xcos `TOWS_c` output, extracted by
`simulate_xcos_model`; none is reconstructed from a plot.

| Group | Signals |
| --- | --- |
| Position and velocity | `x_m`, `y_m`, `z_m`, `vx_mps`, `vy_mps`, `vz_mps` |
| Orbit environment | `altitude_km`, `speed_mps`, `density_kgm3`, `sunlight` |
| Attitude | `q_norm`, `q0`, `q1`, `q2`, `q3`, `wx_rads`, `wy_rads`, `wz_rads` |
| Control and environment torques | `control_x_Nm`, `control_y_Nm`, `control_z_Nm`, `disturbance_x_Nm`, `disturbance_y_Nm`, `disturbance_z_Nm` |

The runner writes the following checked-in artifacts:

- [`coupled_leo.xcos`](coupled_leo.xcos): native Xcos diagram;
- [`coupled_leo.csv`](coupled_leo.csv): aligned numerical telemetry;
- [`summary.json`](summary.json): model constants, MCP provenance, and metrics;
- [`overview.svg`](overview.svg): plot generated from the returned CSV data.

## Verified reference result

The checked-in result was run through real Scilab/Xcos and the MCP. It is a
useful regression reference rather than a claim of flight qualification.

| Check | Result |
| --- | ---: |
| Altitude range | 472.64 to 506.89 km |
| J2 nodal regression observed from state vectors | -0.639° |
| Independent first-order J2 prediction | -0.660° |
| Eclipse fraction | 35.8% |
| Maximum atmospheric density | 1.07e-12 kg/m³ |
| Maximum quaternion-norm error | 3.38e-7 |
| Final attitude error | 0.046° |
| Peak environmental torque | 2.06e-5 N m |
| Peak reaction-wheel torque | 2.49e-3 N m |

The close nodal-regression comparison is an independent check that the J2
term has a physically credible magnitude and sign for this orbit. It does not
validate every force, torque, or controller term.

## Tests

The repository checks both the saved reference data and a short native-Xcos
run:

```bash
uv run pytest -q -m "not integration"
uv run pytest -q tests/integration/test_real_xcos.py::test_coupled_leo_diagram_returns_physical_telemetry_from_native_xcos
```

The integration test validates the native diagram and requests altitude,
quaternion norm, disturbance torque, and wheel-control torque from the real
engine.

## Fidelity boundaries

This is a coupled engineering demonstration, not a mission-validated digital
twin. In particular:

- The smooth exponential atmosphere is not NRLMSIS or a space-weather-driven model.
- The Sun is fixed and the eclipse is cylindrical; there is no penumbra, albedo, or Earth infrared.
- Gravity stops at J2; third-body gravity, tides, and higher-order geopotential terms are omitted.
- Magnetic torque, spacecraft sensors, navigation/estimation, flexible dynamics, wheel momentum storage, and desaturation are omitted.
- Vehicle properties and controller gains are representative, not tied to a flight design.
- Solar wind is an upper-bound direct surface-pressure sensitivity, not a magnetospheric interaction model.

Use this example to exercise and regress the MCP-to-Xcos numerical workflow.
For mission analysis or control-design acceptance, replace these assumptions
with a validated environment, vehicle, actuator, and estimation model.
