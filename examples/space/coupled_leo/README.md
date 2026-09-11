# Coupled low-Earth-orbit simulation

This example exercises the complete path from an MCP client to real
Scilab/Xcos and back to numerical telemetry. The generated native diagram has
16 continuous states, 291 blocks, 442 links, and 24 `TOWS_c` recorders.

## Modelled dynamics

The orbit is propagated in three-dimensional Earth-centred inertial
coordinates from a 480 x 520 km, 51.6 degree orbit. Forces include central
gravity, the oblate-Earth J2 term, drag relative to a co-rotating exponential
thermosphere, eclipse-gated solar-radiation pressure, and a small explicit
solar-wind pressure sensitivity.

The attitude model uses a four-element quaternion, full Euler rigid-body
cross-axis coupling, instantaneous gravity-gradient torque, aerodynamic and
light-pressure centre-of-pressure torques, and three saturated reaction-wheel
torques with first-order actuator dynamics. A nonlinear quaternion feedback
law provides inertial pointing.

Constants and equations are based on public engineering references: the
[NASA GEONS mathematical specification](https://ntrs.nasa.gov/api/citations/20240004259/downloads/GEONSMS_R3_0_NASA-TP-20240004259.pdf)
for Earth/J2 parameters, a [NASA gravity-gradient torque
derivation](https://ntrs.nasa.gov/api/citations/19740022191/downloads/19740022191.pdf),
the [NASA/PDS drag model](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=MPFL-M-ASIMET-4-DDR-EDL-V1.0),
and NASA's [solar-radiation pressure
value](https://www.grc.nasa.gov/WWW/k-12/Numbers/Math/Mathematical_Thinking/sunlight_exerts_pressure.htm).

## Run it

From the repository root, with Scilab/Xcos and `xvfb-run` available:

```bash
PYTHONPATH=src uv run python examples/space/coupled_leo/run.py
```

The runner generates the diagram atomically, starts the MCP server over stdio,
and calls `inspect_xcos_model`, `validate_xcos_model`, and
`simulate_xcos_model`. It writes:

- `coupled_leo.xcos`: the native diagram;
- `coupled_leo.csv`: 24 aligned numerical telemetry channels;
- `overview.svg`: altitude, attitude-error, and torque plots;
- `summary.json`: assumptions and result metrics.

## Checked-in result

The two-orbit, 12,000-second run returned 1,200 samples per channel. Altitude
remained between 472.64 and 506.89 km. The observed right-ascension-of-ascending-
node change was -0.639 degrees, close to the independent first-order J2
prediction of -0.660 degrees. Maximum quaternion-norm error was 3.4e-7 and the
final attitude error was 0.046 degrees. The run crossed eclipse boundaries and
produced density-dependent forces and non-zero environmental torques.

## Fidelity boundaries

This is a coupled engineering demonstration, not a mission-validated digital
twin. The atmosphere is a smooth exponential approximation, not NRLMSIS; the
Sun direction is fixed and eclipse is cylindrical; gravity stops at J2; and
third-body gravity, albedo, Earth infrared, magnetic torque, sensors,
estimation, flexible modes, wheel momentum storage, and desaturation are not
modelled. Vehicle properties and controller gains are representative rather
than tied to a flight design. Solar wind is deliberately treated as an
upper-bound direct surface-pressure sensitivity, not as a magnetospheric
interaction model.
