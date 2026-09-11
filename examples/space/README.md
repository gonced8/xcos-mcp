# Spacecraft examples

These are application-level demonstrations of the generic Xcos MCP. The MCP
itself contains no spacecraft-specific tools, assumptions, or data model.

## Coupled LEO simulation

[`coupled_leo`](coupled_leo/) is the realistic end-to-end case. It propagates
an eccentric, inclined low-Earth orbit together with nonlinear rigid-body
attitude dynamics, environmental forces and torques, and reaction-wheel
control. Its checked-in 12,000-second result was produced by real Scilab/Xcos
and returned numerically through the MCP.

## Educational attitude examples

`attitude_control.xcos` and `attitude_disturbance.xcos` are intentionally small
teaching examples. They are useful for inspecting diagrams and exercising
individual control concepts, but their uncoupled dynamics are not intended as
a realistic spacecraft simulation.
