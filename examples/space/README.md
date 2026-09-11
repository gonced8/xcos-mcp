# Three-axis spacecraft attitude example

This example is a reproducible, representative spacecraft attitude-control
case executed by native Scilab/Xcos through `xcos-mcp`. It is substantially
more realistic than the original one-axis pulse-disturbance example, but it is
still an engineering test case rather than a flight-qualified simulator.

## Model

The model uses independent small-angle roll, pitch, and yaw dynamics:

```text
theta_dot = omega
I * omega_dot = reaction_wheel_torque + disturbance_torque
reaction_wheel_torque_dot =
    (saturate(-Kp * theta - Kd * omega) - reaction_wheel_torque) / 0.15 s
```

The principal inertias are 120, 100, and 80 kg m^2. Initial attitude errors
are 5, -3, and 8 degrees, with non-zero initial body rates. Each reaction wheel
has a symmetric 0.08 N m command limit and a first-order torque response.

The deterministic disturbance environment combines:

- gravity-gradient torque at twice the representative orbital rate;
- aerodynamic torque at the orbital rate;
- solar-radiation-pressure torque at half the orbital rate;
- residual-magnetic-dipole torque at three times the orbital rate;
- reaction-wheel imbalance at 0.20 rad/s;
- a fixed axis-dependent bias.

The orbital rate, 0.0011068 rad/s, represents a circular orbit near 500 km.
Axis-specific phases and amplitude scaling prevent the three torque histories
from being identical. Deterministic terms make repeated regression runs
exactly comparable.

## Run it

From the repository root:

```bash
PYTHONPATH=src uv run python examples/space/run_realistic_satellite.py
```

The runner constructs the `.xcos` file with native installed blocks, starts the
MCP server over stdio, and calls `inspect_xcos_model`, `validate_xcos_model`,
and `simulate_xcos_model`. It then writes:

- `realistic_satellite_attitude.xcos`: the 138-block native diagram;
- `realistic_satellite_attitude.csv`: aligned numerical output;
- `realistic_satellite_attitude.svg`: attitude, control, and disturbance plots;
- `realistic_satellite_summary.json`: assumptions and result metrics.

The checked-in 12,000-second run contains 12,000 native samples per signal.
The CSV and plot retain 6,000 evenly selected samples returned by the MCP.

## Checked-in result

After the initial transient, RMS pointing error from 600 seconds onward was
0.0192 degrees in roll, 0.0188 degrees in pitch, and 0.0329 degrees in yaw.
Peak environmental torque was 35.5 micro-newton-metres. The largest commanded
reaction-wheel torque was 0.00722 N m, below its 0.08 N m limit.

## Boundaries

The model does not yet include nonlinear quaternion kinematics, cross-axis
gyroscopic coupling, a propagated orbit, eclipses, stochastic sensor noise,
flexible modes, wheel momentum storage/desaturation, or estimator dynamics.
Those are the next steps before calling it a high-fidelity spacecraft digital
twin.
