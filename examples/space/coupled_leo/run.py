# SPDX-License-Identifier: GPL-3.0-only
"""Build and run a coupled LEO orbit/attitude model through the generic MCP."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, NamedTuple

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from xcos_mcp.process import run_scilab_script, wait_for_files


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL_PATH = HERE / "coupled_leo.xcos"
CSV_PATH = HERE / "coupled_leo.csv"
SUMMARY_PATH = HERE / "summary.json"
PLOT_PATH = HERE / "overview.svg"

DURATION = 12_000.0
SAMPLE_PERIOD = 10.0
MAX_SAMPLES = 5_000
BUFFER_SIZE = int(DURATION / SAMPLE_PERIOD) + 100

# SI units throughout.
MU = 3.986004415e14
EARTH_RADIUS = 6_378_137.0
J2 = 1.08262668e-3
EARTH_RATE = 7.2921150e-5
MASS = 250.0
DRAG_AREA = 1.2
SOLAR_AREA = 1.6
CD = 2.2
CR = 1.5
SOLAR_PRESSURE = 4.56e-6
SOLAR_WIND_PRESSURE = 2.0e-9
RHO_500_KM = 6.967e-13
DENSITY_SCALE_HEIGHT = 63_822.0
INERTIA = (28.0, 42.0, 35.0)
AERO_COP = (0.08, -0.03, 0.02)
LIGHT_COP = (-0.05, 0.04, 0.01)
KP = (0.020, 0.024, 0.018)
KD = (1.20, 1.35, 1.05)
WHEEL_TORQUE_LIMIT = 0.08
WHEEL_TIME_CONSTANT = 0.15


class Signal(NamedTuple):
    block: int
    port: int = 1


class Diagram:
    """Generate native Scicos blocks and insert fan-out blocks automatically."""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.connections: list[tuple[Signal, int, int, bool]] = []

    def block(self, interface: str, x: float, y: float, commands: list[str], label: str) -> Signal:
        index = len(self.blocks) + 1
        statements = [
            f'scs_m.objs({index}) = {interface}("define");',
            f"scs_m.objs({index}).graphics.orig = [{x:g} {y:g}];",
            f'scs_m.objs({index}).graphics.id = "{label}";',
            *[
                command[1:] if command.startswith("!") else f"scs_m.objs({index}).{command}"
                for command in commands
            ],
        ]
        self.blocks.append("\n".join(statements))
        return Signal(index)

    def connect(self, source: Signal, target: Signal, target_port: int = 1, *, event: bool = False) -> None:
        self.connections.append((source, target.block, target_port, event))

    def integrator(self, initial: float, x: float, y: float, label: str) -> Signal:
        return self.block(
            "INTEGRAL_m",
            x,
            y,
            [
                f"model.state = {initial:.17g};",
                f"graphics.exprs = string([{initial:.17g};0;0;1;-1]);",
            ],
            label,
        )

    def expression(
        self,
        inputs: list[Signal],
        formula: str,
        x: float,
        y: float,
        label: str,
        *,
        zero_crossing: bool = False,
    ) -> Signal:
        index = len(self.blocks) + 1
        arguments = ",".join(f"u{number}" for number in range(1, len(inputs) + 1))
        use_zero = 1 if zero_crossing else 0
        commands = [
            f'!deff("__xcos_expr_{index}({arguments})", "{formula}");',
            f"![__ok_{index},__ipar_{index},__rpar_{index},__nz_{index}]=compile_expr(__xcos_expr_{index});",
            f'!if ~__ok_{index} then error("Cannot compile expression {label}"); end',
            f'!mputl("{label}", getenv("XCOS_MCP_PROGRESS_PATH"));',
            f"!scs_m.objs({index}).model.in = ones({len(inputs)},1);",
            f"!scs_m.objs({index}).model.in2 = ones({len(inputs)},1);",
            f"!scs_m.objs({index}).model.intyp = ones({len(inputs)},1);",
            f"!scs_m.objs({index}).model.rpar = __rpar_{index};",
            f"!scs_m.objs({index}).model.ipar = __ipar_{index};",
            f"!scs_m.objs({index}).model.nzcross = {use_zero}*__nz_{index};",
            f"!scs_m.objs({index}).model.nmode = {use_zero}*__nz_{index};",
            f"!scs_m.objs({index}).graphics.pin = zeros({len(inputs)},1);",
            f'!scs_m.objs({index}).graphics.exprs = ["{len(inputs)}";"{formula}";"{use_zero}"];',
        ]
        signal = self.block("EXPRESSION", x, y, commands, label)
        for port, source in enumerate(inputs, start=1):
            self.connect(source, signal, port)
        return signal

    def saturation(self, source: Signal, limit: float, x: float, y: float, label: str) -> Signal:
        result = self.block(
            "SATURATION",
            x,
            y,
            [
                f"model.rpar = [{limit:.17g};{-limit:.17g}];",
                f"graphics.exprs = string([{limit:.17g};{-limit:.17g};1]);",
            ],
            label,
        )
        self.connect(source, result)
        return result

    def recorder(self, source: Signal, name: str, x: float, y: float) -> None:
        recorder = self.block(
            "TOWS_c",
            x,
            y,
            [
                f'model.ipar = [{BUFFER_SIZE};length(ascii("{name}"));ascii("{name}")\'];',
                f'graphics.exprs = ["{BUFFER_SIZE}";"{name}";"0"];',
            ],
            name,
        )
        clock = self.block(
            "CLOCK_c",
            x,
            y + 45,
            [
                f'model.rpar.objs(2).graphics.exprs = ["{SAMPLE_PERIOD:g}";"0"];',
                f"model.rpar.objs(2).model.rpar = [{SAMPLE_PERIOD:g};0];",
                "model.rpar.objs(2).model.firing = 0;",
            ],
            f"sample_{name}",
        )
        self.connect(source, recorder)
        self.connect(clock, recorder, event=True)

    def _expanded_connections(self) -> list[tuple[Signal, int, int, bool]]:
        groups: dict[tuple[Signal, bool], list[tuple[int, int]]] = {}
        for source, target, target_port, event in self.connections:
            groups.setdefault((source, event), []).append((target, target_port))

        expanded: list[tuple[Signal, int, int, bool]] = []
        for (source, event), targets in groups.items():
            if event or len(targets) == 1:
                expanded.extend((source, target, port, event) for target, port in targets)
                continue
            remaining = list(targets)
            upstream = source
            while len(remaining) > 1:
                splitter = self.block("SPLIT_f", 0, 0, [], f"fanout_{len(self.blocks) + 1}")
                expanded.append((upstream, splitter.block, 1, False))
                take = len(remaining) if len(remaining) <= 3 else 2
                for output_port in range(1, take + 1):
                    target, target_port = remaining.pop(0)
                    expanded.append((Signal(splitter.block, output_port), target, target_port, False))
                upstream = Signal(splitter.block, 3)
            if remaining:
                target, target_port = remaining.pop()
                expanded.append((upstream, target, target_port, False))
        return expanded

    def emit(self) -> str:
        connections = self._expanded_connections()
        lines = [
            "mode(-1);",
            "lines(0);",
            "loadXcosLibs();",
            "loadScicos();",
            'exec(SCI+"/modules/scicos_blocks/macros/NonLinear/EXPRESSION.sci", -1);',
            "scs_m = scicos_diagram();",
            f"scs_m.props.tf = {DURATION:.17g};",
            "scs_m.props.tol = [1e-7;1e-7;1e-10;60;0;1;10];",
            'scs_m.props.title = "Coupled LEO orbit and attitude dynamics";',
            *self.blocks,
        ]
        first_link = len(self.blocks) + 1
        for offset, (source, target, target_port, event) in enumerate(connections):
            link = first_link + offset
            if event:
                lines.extend([
                    f"scs_m.objs({link}) = scicos_link(from=[{source.block} {source.port} 0], to=[{target} {target_port} 1], ct=[1 -1]);",
                    f"scs_m.objs({source.block}).graphics.peout({source.port}) = {link};",
                    f"scs_m.objs({target}).graphics.pein({target_port}) = {link};",
                ])
            else:
                lines.extend([
                    f"scs_m.objs({link}) = scicos_link(from=[{source.block} {source.port} 0], to=[{target} {target_port} 1]);",
                    f"scs_m.objs({source.block}).graphics.pout({source.port}) = {link};",
                    f"scs_m.objs({target}).graphics.pin({target_port}) = {link};",
                ])
        lines.extend([
            'mputl("export", getenv("XCOS_MCP_PROGRESS_PATH"));',
            'xcosDiagramToScilab(getenv("XCOS_MCP_MODEL_PATH"), scs_m);',
            "exit(0);",
        ])
        return "\n".join(lines)


def _initial_state() -> dict[str, float]:
    perigee = EARTH_RADIUS + 480_000.0
    apogee = EARTH_RADIUS + 520_000.0
    semimajor = (perigee + apogee) / 2
    speed = math.sqrt(MU * (2 / perigee - 1 / semimajor))
    inclination = math.radians(51.6)
    roll, pitch, yaw = map(math.radians, (5.0, -3.0, 8.0))
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return {
        "x": perigee,
        "y": 0.0,
        "z": 0.0,
        "vx": 0.0,
        "vy": speed * math.cos(inclination),
        "vz": speed * math.sin(inclination),
        "q0": cr * cp * cy + sr * sp * sy,
        "q1": sr * cp * cy - cr * sp * sy,
        "q2": cr * sp * cy + sr * cp * sy,
        "q3": cr * cp * sy - sr * sp * cy,
        "wx": math.radians(0.05),
        "wy": math.radians(-0.03),
        "wz": math.radians(0.04),
        "tx": 0.0,
        "ty": 0.0,
        "tz": 0.0,
    }


def build_model() -> None:
    progress_path = ROOT / ".xcos-mcp" / "coupled-leo-build-progress.txt"
    temporary_model = ROOT / ".xcos-mcp" / "coupled-leo-next.xcos"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.unlink(missing_ok=True)
    temporary_model.unlink(missing_ok=True)
    d = Diagram()
    initial = _initial_state()
    state = {
        name: d.integrator(value, 60 + (index % 4) * 120, 60 + (index // 4) * 90, name)
        for index, (name, value) in enumerate(initial.items())
    }

    r = d.expression([state["x"], state["y"], state["z"]], "(u1^2+u2^2+u3^2)^0.5", 600, 50, "radius")
    altitude = d.expression([r], f"u1-{EARTH_RADIUS:.17g}", 730, 50, "altitude")
    density = d.expression(
        [altitude],
        f"{RHO_500_KM:.17g}*exp(-(u1-500000)/{DENSITY_SCALE_HEIGHT:.17g})",
        860,
        50,
        "density",
    )
    vrel_x = d.expression([state["vx"], state["y"]], f"u1+{EARTH_RATE:.17g}*u2", 600, 130, "vrel_x")
    vrel_y = d.expression([state["vy"], state["x"]], f"u1-{EARTH_RATE:.17g}*u2", 600, 170, "vrel_y")
    vrel_z = state["vz"]
    vrel = d.expression([vrel_x, vrel_y, vrel_z], "(u1^2+u2^2+u3^2)^0.5", 740, 150, "vrel")
    shadow = d.expression(
        [state["x"], state["y"], state["z"]],
        f"1-((u1<0)&((u2^2+u3^2)<{EARTH_RADIUS ** 2:.17g}))",
        860,
        120,
        "sunlight",
        zero_crossing=True,
    )

    drag_factor = 0.5 * CD * DRAG_AREA / MASS
    pressure_scale = SOLAR_AREA / MASS
    accelerations: dict[str, Signal] = {}
    for axis, coordinate, relative in (
        ("x", state["x"], vrel_x),
        ("y", state["y"], vrel_y),
        ("z", state["z"], vrel_z),
    ):
        j2_shape = "1-5*(u3/u1)^2" if axis != "z" else "3-5*(u3/u1)^2"
        light = (
            f"+{pressure_scale:.17g}*({CR * SOLAR_PRESSURE:.17g}*u7+{SOLAR_WIND_PRESSURE:.17g})"
            if axis == "x"
            else ""
        )
        formula = (
            f"-{MU:.17g}*u2/u1^3*(1+1.5*{J2:.17g}*({EARTH_RADIUS:.17g}/u1)^2*({j2_shape}))"
            f"-{drag_factor:.17g}*u4*u5*u6{light}"
        )
        accelerations[axis] = d.expression(
            [r, coordinate, state["z"], density, vrel, relative, shadow],
            formula,
            1010,
            70 + 60 * len(accelerations),
            f"accel_{axis}_j2_drag_light",
        )

    for axis in "xyz":
        d.connect(state[f"v{axis}"], state[axis])
        d.connect(accelerations[axis], state[f"v{axis}"])

    q = [state[f"q{index}"] for index in range(4)]
    omega = [state[name] for name in ("wx", "wy", "wz")]
    q_formulas = (
        "-0.5*(u5*u2+u6*u3+u7*u4)",
        "0.5*(u5*u1+u7*u3-u6*u4)",
        "0.5*(u6*u1-u7*u2+u5*u4)",
        "0.5*(u7*u1+u6*u2-u5*u3)",
    )
    for index, formula in enumerate(q_formulas):
        derivative = d.expression([*q, *omega], formula, 600, 300 + index * 45, f"q{index}_dot")
        d.connect(derivative, q[index])

    qn = d.expression(q, "u1^2+u2^2+u3^2+u4^2", 760, 310, "quaternion_norm_squared")
    r_body_formulas = (
        "(1-2*(u7^2+u8^2)/u4)*u1+2*(u6*u7+u5*u8)/u4*u2+2*(u6*u8-u5*u7)/u4*u3",
        "2*(u6*u7-u5*u8)/u4*u1+(1-2*(u6^2+u8^2)/u4)*u2+2*(u7*u8+u5*u6)/u4*u3",
        "2*(u6*u8+u5*u7)/u4*u1+2*(u7*u8-u5*u6)/u4*u2+(1-2*(u6^2+u7^2)/u4)*u3",
    )
    rb = [
        d.expression([state["x"], state["y"], state["z"], qn, *q], formula, 930, 300 + i * 45, f"r_body_{i}")
        for i, formula in enumerate(r_body_formulas)
    ]

    gg = []
    gg_inertia = (INERTIA[2] - INERTIA[1], INERTIA[0] - INERTIA[2], INERTIA[1] - INERTIA[0])
    products = ((rb[1], rb[2]), (rb[2], rb[0]), (rb[0], rb[1]))
    for i, ((left, right), delta_i) in enumerate(zip(products, gg_inertia)):
        gg.append(d.expression([r, left, right], f"3*{MU:.17g}*{delta_i:.17g}*u2*u3/u1^5", 1090, 300 + i * 45, f"gravity_gradient_{i}"))

    drag_force = [
        d.expression([density, vrel, component], f"-{0.5 * CD * DRAG_AREA:.17g}*u1*u2*u3", 600, 520 + i * 45, f"drag_force_{i}")
        for i, component in enumerate((vrel_x, vrel_y, vrel_z))
    ]
    dcm_force_formulas = (
        "(1-2*(u7^2+u8^2)/u4)*u1+2*(u6*u7+u5*u8)/u4*u2+2*(u6*u8-u5*u7)/u4*u3",
        "2*(u6*u7-u5*u8)/u4*u1+(1-2*(u6^2+u8^2)/u4)*u2+2*(u7*u8+u5*u6)/u4*u3",
        "2*(u6*u8+u5*u7)/u4*u1+2*(u7*u8-u5*u6)/u4*u2+(1-2*(u6^2+u7^2)/u4)*u3",
    )
    drag_body = [
        d.expression([*drag_force, qn, *q], formula, 760, 520 + i * 45, f"drag_body_{i}")
        for i, formula in enumerate(dcm_force_formulas)
    ]
    light_force = (
        f"{SOLAR_AREA:.17g}*({CR * SOLAR_PRESSURE:.17g}*u1+{SOLAR_WIND_PRESSURE:.17g})"
    )
    light_body = [
        d.expression(
            [shadow, qn, *q],
            formula,
            920,
            520 + i * 45,
            f"light_body_{i}",
        )
        for i, formula in enumerate((
            f"({light_force})*(1-2*(u5^2+u6^2)/u2)",
            f"({light_force})*2*(u4*u5-u3*u6)/u2",
            f"({light_force})*2*(u4*u6+u3*u5)/u2",
        ))
    ]

    def cross_torque(force: list[Signal], lever: tuple[float, float, float], prefix: str, y: float) -> list[Signal]:
        return [
            d.expression([force[1], force[2]], f"{lever[1]:.17g}*u2-{lever[2]:.17g}*u1", 1080, y, f"{prefix}_x"),
            d.expression([force[2], force[0]], f"{lever[2]:.17g}*u2-{lever[0]:.17g}*u1", 1080, y + 45, f"{prefix}_y"),
            d.expression([force[0], force[1]], f"{lever[0]:.17g}*u2-{lever[1]:.17g}*u1", 1080, y + 90, f"{prefix}_z"),
        ]

    aero_torque = cross_torque(drag_body, AERO_COP, "aero_torque", 520)
    light_torque = cross_torque(light_body, LIGHT_COP, "light_torque", 680)
    disturbance = [
        d.expression([gg[i], aero_torque[i], light_torque[i]], "u1+u2+u3", 1250, 420 + i * 55, f"disturbance_{i}")
        for i in range(3)
    ]

    controls = []
    for i, axis in enumerate("xyz"):
        command = d.expression([q[i + 1], omega[i]], f"-{2 * KP[i]:.17g}*u1-{KD[i]:.17g}*u2", 600, 850 + i * 60, f"wheel_command_{axis}")
        limited = d.saturation(command, WHEEL_TORQUE_LIMIT, 760, 850 + i * 60, f"wheel_limit_{axis}")
        lag = d.expression([limited, state[f"t{axis}"]], f"(u1-u2)/{WHEEL_TIME_CONSTANT:.17g}", 900, 850 + i * 60, f"wheel_lag_{axis}")
        d.connect(lag, state[f"t{axis}"])
        controls.append(state[f"t{axis}"])

    coupling = ((omega[1], omega[2], INERTIA[2] - INERTIA[1]), (omega[2], omega[0], INERTIA[0] - INERTIA[2]), (omega[0], omega[1], INERTIA[1] - INERTIA[0]))
    for i, axis in enumerate("xyz"):
        derivative = d.expression(
            [controls[i], disturbance[i], coupling[i][0], coupling[i][1]],
            f"(u1+u2-{coupling[i][2]:.17g}*u3*u4)/{INERTIA[i]:.17g}",
            1080,
            850 + i * 60,
            f"omega_dot_{axis}",
        )
        d.connect(derivative, omega[i])

    altitude_km = d.expression([altitude], "u1/1000", 1280, 810, "altitude_km")
    speed = d.expression([state["vx"], state["vy"], state["vz"]], "(u1^2+u2^2+u3^2)^0.5", 1280, 860, "speed")
    qnorm = d.expression([qn], "u1^0.5", 1280, 910, "quaternion_norm")

    telemetry = {
        "x_m": state["x"], "y_m": state["y"], "z_m": state["z"],
        "vx_mps": state["vx"], "vy_mps": state["vy"], "vz_mps": state["vz"],
        "altitude_km": altitude_km, "speed_mps": speed, "density_kgm3": density,
        "sunlight": shadow, "q_norm": qnorm,
        "q0": q[0], "q1": q[1], "q2": q[2], "q3": q[3],
        "wx_rads": omega[0], "wy_rads": omega[1], "wz_rads": omega[2],
        "control_x_Nm": controls[0], "control_y_Nm": controls[1], "control_z_Nm": controls[2],
        "disturbance_x_Nm": disturbance[0], "disturbance_y_Nm": disturbance[1], "disturbance_z_Nm": disturbance[2],
    }
    for index, (name, signal) in enumerate(telemetry.items()):
        d.recorder(signal, name, 1460 + (index % 3) * 100, 40 + (index // 3) * 110)

    run_scilab_script(
        d.emit(),
        600.0,
        gui=True,
        environment={
            "XCOS_MCP_MODEL_PATH": str(temporary_model),
            "XCOS_MCP_PROGRESS_PATH": str(progress_path),
        },
    )
    if not wait_for_files([temporary_model], 20.0):
        raise RuntimeError("Xcos did not export the coupled satellite model")
    os.replace(temporary_model, MODEL_PATH)


async def call_mcp() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xcos_mcp"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                response = await session.call_tool(name, arguments)
                if response.isError:
                    raise RuntimeError(response.content[0].text)
                return json.loads(response.content[0].text)

            inspection = await call("inspect_xcos_model", {"model_path": str(MODEL_PATH)})
            validation = await call("validate_xcos_model", {"model_path": str(MODEL_PATH), "timeout_seconds": 180})
            simulation = await call("simulate_xcos_model", {
                "model_path": str(MODEL_PATH),
                "duration_seconds": DURATION,
                "outputs": inspection["recorded_outputs"],
                "timeout_seconds": 600,
                "max_samples": MAX_SAMPLES,
            })
            return inspection, validation, simulation


def _unwrap(values: list[float]) -> list[float]:
    result = [values[0]]
    for value in values[1:]:
        while value - result[-1] > math.pi:
            value -= 2 * math.pi
        while value - result[-1] < -math.pi:
            value += 2 * math.pi
        result.append(value)
    return result


def summarize(inspection: dict[str, Any], validation: dict[str, Any], simulation: dict[str, Any]) -> dict[str, Any]:
    signals = simulation["signals"]
    attitude_error = [
        math.degrees(2 * math.atan2(math.sqrt(q1**2 + q2**2 + q3**2), abs(q0)))
        for q0, q1, q2, q3 in zip(signals["q0"], signals["q1"], signals["q2"], signals["q3"])
    ]
    x, y, z = (signals[name] for name in ("x_m", "y_m", "z_m"))
    vx, vy, vz = (signals[name] for name in ("vx_mps", "vy_mps", "vz_mps"))
    raan = _unwrap([
        math.atan2(y_i * vz_i - z_i * vy_i, -(z_i * vx_i - x_i * vz_i))
        for x_i, y_i, z_i, vx_i, vy_i, vz_i in zip(x, y, z, vx, vy, vz)
    ])
    perigee = EARTH_RADIUS + 480_000.0
    apogee = EARTH_RADIUS + 520_000.0
    semimajor = (perigee + apogee) / 2
    eccentricity = (apogee - perigee) / (apogee + perigee)
    p = semimajor * (1 - eccentricity**2)
    inclination = math.radians(51.6)
    expected_raan_rate = -1.5 * J2 * math.sqrt(MU / semimajor**3) * (EARTH_RADIUS / p) ** 2 * math.cos(inclination)
    summary = {
        "engine": simulation["engine"],
        "mcp_tools_used": ["inspect_xcos_model", "validate_xcos_model", "simulate_xcos_model"],
        "model_imported": validation["imported"],
        "duration_seconds": simulation["duration_seconds"],
        "sample_period_seconds": SAMPLE_PERIOD,
        "returned_samples": len(simulation["time"]),
        "block_count": len(inspection["blocks"]),
        "link_count": len(inspection["links"]),
        "physics": {
            "orbit": "3D Cartesian propagation with central gravity and J2",
            "atmosphere": "co-rotating exponential thermosphere calibrated at 500 km",
            "surface_forces": "density-dependent drag, eclipse-gated solar radiation plus solar-wind pressure",
            "attitude": "nonlinear quaternion kinematics and Euler rigid-body coupling",
            "torques": "gravity gradient, aerodynamic centre-of-pressure, photon and particle pressure",
            "actuator": "three saturated first-order reaction-wheel torque channels",
        },
        "constants": {
            "mu_m3_s2": MU, "earth_equatorial_radius_m": EARTH_RADIUS, "J2": J2,
            "earth_rotation_rad_s": EARTH_RATE, "solar_pressure_Pa": SOLAR_PRESSURE,
            "solar_wind_pressure_Pa": SOLAR_WIND_PRESSURE, "mass_kg": MASS,
        },
        "metrics": {
            "minimum_altitude_km": min(signals["altitude_km"]),
            "maximum_altitude_km": max(signals["altitude_km"]),
            "final_altitude_km": signals["altitude_km"][-1],
            "observed_raan_change_deg": math.degrees(raan[-1] - raan[0]),
            "first_order_J2_raan_change_deg": math.degrees(expected_raan_rate * DURATION),
            "maximum_density_kg_m3": max(signals["density_kgm3"]),
            "eclipse_fraction": sum(value < 0.5 for value in signals["sunlight"]) / len(signals["sunlight"]),
            "maximum_quaternion_norm_error": max(abs(value - 1) for value in signals["q_norm"]),
            "final_attitude_error_deg": attitude_error[-1],
            "maximum_attitude_error_deg": max(attitude_error),
            "peak_control_torque_Nm": max(abs(value) for axis in "xyz" for value in signals[f"control_{axis}_Nm"]),
            "peak_environmental_torque_Nm": max(abs(value) for axis in "xyz" for value in signals[f"disturbance_{axis}_Nm"]),
        },
    }
    return summary


def write_csv(simulation: dict[str, Any]) -> None:
    names = list(simulation["signals"])
    with CSV_PATH.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        writer.writerow(["time_s", *names])
        writer.writerows(zip(simulation["time"], *(simulation["signals"][name] for name in names)))


def write_svg(simulation: dict[str, Any]) -> None:
    time = simulation["time"]
    signals = simulation["signals"]
    attitude_error = [
        math.degrees(2 * math.atan2(math.sqrt(q1**2 + q2**2 + q3**2), abs(q0)))
        for q0, q1, q2, q3 in zip(signals["q0"], signals["q1"], signals["q2"], signals["q3"])
    ]
    width, height = 1200, 760
    panels = [
        ("Altitude (km)", [signals["altitude_km"]], ["#58a6ff"]),
        ("Attitude error (deg)", [attitude_error], ["#f0883e"]),
        ("Environmental torque (uN m)", [[1e6 * v for v in signals[f"disturbance_{axis}_Nm"]] for axis in "xyz"], ["#3fb950", "#d2a8ff", "#ff7b72"]),
    ]
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#0d1117"/>', '<text x="55" y="38" fill="#f0f6fc" font-family="sans-serif" font-size="24">Coupled LEO orbit and attitude simulation</text>']
    for panel, (title, series, colors) in enumerate(panels):
        top = 65 + panel * 225
        left, plot_width, plot_height = 70, 1080, 170
        values = [value for trace in series for value in trace]
        low, high = min(values), max(values)
        if math.isclose(low, high):
            low, high = low - 1, high + 1
        elements.extend([f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="#161b22" stroke="#30363d"/>', f'<text x="{left}" y="{top - 10}" fill="#c9d1d9" font-family="sans-serif" font-size="16">{title}</text>'])
        for trace, color in zip(series, colors):
            points = " ".join(
                f"{left + plot_width * t / time[-1]:.2f},{top + plot_height * (high - value) / (high - low):.2f}"
                for t, value in zip(time, trace)
            )
            elements.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{points}"/>')
        elements.append(f'<text x="{left + 5}" y="{top + 17}" fill="#8b949e" font-family="monospace" font-size="12">{high:.4g}</text>')
        elements.append(f'<text x="{left + 5}" y="{top + plot_height - 5}" fill="#8b949e" font-family="monospace" font-size="12">{low:.4g}</text>')
    elements.append('</svg>')
    PLOT_PATH.write_text("\n".join(elements), encoding="utf-8")


def main() -> None:
    build_model()
    inspection, validation, simulation = asyncio.run(call_mcp())
    write_csv(simulation)
    write_svg(simulation)
    summary = summarize(inspection, validation, simulation)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
