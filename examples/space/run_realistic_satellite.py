# SPDX-License-Identifier: GPL-3.0-only
"""Build and run a representative three-axis spacecraft attitude case via MCP."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from xcos_mcp.process import run_scilab_script


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent
MODEL_PATH = OUTPUT_DIR / "realistic_satellite_attitude.xcos"
CSV_PATH = OUTPUT_DIR / "realistic_satellite_attitude.csv"
SUMMARY_PATH = OUTPUT_DIR / "realistic_satellite_summary.json"
PLOT_PATH = OUTPUT_DIR / "realistic_satellite_attitude.svg"

DURATION_SECONDS = 12_000.0
SAMPLE_PERIOD_SECONDS = 1.0
RETURNED_SAMPLES = 6_000
BUFFER_SIZE = int(DURATION_SECONDS / SAMPLE_PERIOD_SECONDS) + 100

# Representative 12U-class spacecraft properties and controller settings.
AXES = {
    "roll": {
        "inertia": 120.0,
        "initial_angle_deg": 5.0,
        "initial_rate_deg_s": 0.05,
        "kp": 0.048,
        "kd": 3.84,
        "phase": 0.0,
        "bias": 1.5e-6,
    },
    "pitch": {
        "inertia": 100.0,
        "initial_angle_deg": -3.0,
        "initial_rate_deg_s": -0.03,
        "kp": 0.040,
        "kd": 3.20,
        "phase": 1.1,
        "bias": -1.0e-6,
    },
    "yaw": {
        "inertia": 80.0,
        "initial_angle_deg": 8.0,
        "initial_rate_deg_s": 0.04,
        "kp": 0.032,
        "kd": 2.56,
        "phase": 2.2,
        "bias": 0.8e-6,
    },
}

ORBITAL_RATE_RAD_S = 0.0011068  # Circular orbit near 500 km altitude.
ACTUATOR_LIMIT_NM = 0.08
ACTUATOR_TIME_CONSTANT_SECONDS = 0.15

# Each term is deterministic, making regression runs exactly reproducible.
DISTURBANCES = (
    ("gravity_gradient", 18.0e-6, 2.0 * ORBITAL_RATE_RAD_S, 0.0),
    ("aerodynamic", 12.0e-6, ORBITAL_RATE_RAD_S, 0.7),
    ("solar_pressure", 3.0e-6, 0.5 * ORBITAL_RATE_RAD_S, 1.4),
    ("magnetic", 6.0e-6, 3.0 * ORBITAL_RATE_RAD_S, 2.1),
    ("wheel_imbalance", 2.0e-6, 0.20, 0.3),
)


class Diagram:
    """Emit a native Scicos diagram while keeping object/link indices consistent."""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.connections: list[tuple[int, int, int, int, bool]] = []

    def block(self, interface: str, x: float, y: float, commands: list[str], label: str) -> int:
        index = len(self.blocks) + 1
        body = [
            f'scs_m.objs({index}) = {interface}("define");',
            f"scs_m.objs({index}).graphics.orig = [{x:g} {y:g}];",
            f'scs_m.objs({index}).graphics.id = "{label}";',
            *[f"scs_m.objs({index}).{command}" for command in commands],
        ]
        self.blocks.append("\n".join(body))
        return index

    def connect(self, source: int, target: int, source_port: int = 1, target_port: int = 1) -> None:
        self.connections.append((source, source_port, target, target_port, False))

    def connect_event(self, source: int, target: int) -> None:
        self.connections.append((source, 1, target, 1, True))

    def gain(self, value: float, x: float, y: float, label: str) -> int:
        return self.block(
            "GAINBLK",
            x,
            y,
            [f"model.rpar = {value:.17g};", f"graphics.exprs = string({value:.17g});"],
            label,
        )

    def summation(self, signs: tuple[int, int], x: float, y: float, label: str) -> int:
        encoded = ";".join(str(sign) for sign in signs)
        return self.block(
            "SUMMATION",
            x,
            y,
            [f"model.ipar = [{encoded}];", f'graphics.exprs = "[{encoded}]";'],
            label,
        )

    def integrator(self, initial: float, x: float, y: float, label: str) -> int:
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

    def saturation(self, limit: float, x: float, y: float, label: str) -> int:
        return self.block(
            "SATURATION",
            x,
            y,
            [
                f"model.rpar = [{limit:.17g};{-limit:.17g}];",
                f"graphics.exprs = string([{limit:.17g};{-limit:.17g};1]);",
            ],
            label,
        )

    def constant(self, value: float, x: float, y: float, label: str) -> int:
        return self.block(
            "CONST_m",
            x,
            y,
            [f"model.rpar = {value:.17g};", f"graphics.exprs = string({value:.17g});"],
            label,
        )

    def sine(self, amplitude: float, frequency: float, phase: float, x: float, y: float, label: str) -> int:
        return self.block(
            "GENSIN_f",
            x,
            y,
            [
                f"model.rpar = [{amplitude:.17g};{frequency:.17g};{phase:.17g}];",
                f"graphics.exprs = string([{amplitude:.17g};{frequency:.17g};{phase:.17g}]);",
            ],
            label,
        )

    def recorder(self, name: str, x: float, y: float) -> int:
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
            y + 55,
            [
                f'model.rpar.objs(2).graphics.exprs = ["{SAMPLE_PERIOD_SECONDS:g}";"0"];',
                f"model.rpar.objs(2).model.rpar = [{SAMPLE_PERIOD_SECONDS:g};0];",
                "model.rpar.objs(2).model.firing = 0;",
            ],
            f"sample_{name}",
        )
        self.connect_event(clock, recorder)
        return recorder

    def split(self, x: float, y: float, label: str) -> int:
        return self.block("SPLIT_f", x, y, [], label)

    def emit(self) -> str:
        lines = [
            "mode(-1);",
            "lines(0);",
            "loadXcosLibs();",
            "loadScicos();",
            "scs_m = scicos_diagram();",
            f"scs_m.props.tf = {DURATION_SECONDS:.17g};",
            'scs_m.props.title = "Three-axis spacecraft attitude with environmental torques";',
            *self.blocks,
        ]
        first_link = len(self.blocks) + 1
        for offset, (source, source_port, target, target_port, event) in enumerate(self.connections):
            link = first_link + offset
            if event:
                lines.extend(
                    [
                        f"scs_m.objs({link}) = scicos_link("
                        f"from=[{source} {source_port} 0], "
                        f"to=[{target} {target_port} 1], ct=[1 -1]);",
                        f"scs_m.objs({source}).graphics.peout({source_port}) = {link};",
                        f"scs_m.objs({target}).graphics.pein({target_port}) = {link};",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"scs_m.objs({link}) = scicos_link("
                        f"from=[{source} {source_port} 0], "
                        f"to=[{target} {target_port} 1]);",
                        f"scs_m.objs({source}).graphics.pout({source_port}) = {link};",
                        f"scs_m.objs({target}).graphics.pin({target_port}) = {link};",
                    ]
                )
        lines.extend(
            [
                'xcosDiagramToScilab(getenv("XCOS_MCP_MODEL_PATH"), scs_m);',
                "exit(0);",
            ]
        )
        return "\n".join(lines)


def pairwise_sum(diagram: Diagram, sources: list[int], x: float, y: float, label: str) -> int:
    result = sources[0]
    for offset, source in enumerate(sources[1:], start=1):
        addition = diagram.summation((1, 1), x + offset * 55, y, f"{label}_{offset}")
        diagram.connect(result, addition, target_port=1)
        diagram.connect(source, addition, target_port=2)
        result = addition
    return result


def build_model() -> None:
    diagram = Diagram()
    for axis_index, (axis, parameters) in enumerate(AXES.items()):
        y = 80.0 + axis_index * 420.0
        phase = float(parameters["phase"])
        disturbance_sources = [
            diagram.constant(float(parameters["bias"]), 20, y + 250, f"{axis}_bias")
        ]
        for disturbance_index, (name, amplitude, frequency, base_phase) in enumerate(DISTURBANCES):
            # Axis scaling and phase offsets avoid three identical torque histories.
            axis_scale = (1.0, 0.82, 1.15)[axis_index]
            disturbance_sources.append(
                diagram.sine(
                    amplitude * axis_scale,
                    frequency,
                    base_phase + phase,
                    20 + disturbance_index * 55,
                    y + 320,
                    f"{axis}_{name}",
                )
            )
        disturbance = pairwise_sum(diagram, disturbance_sources, 300, y + 285, f"{axis}_disturbance_sum")

        kp = diagram.gain(-float(parameters["kp"]), 410, y, f"{axis}_minus_kp")
        kd = diagram.gain(-float(parameters["kd"]), 410, y + 80, f"{axis}_minus_kd")
        command_sum = diagram.summation((1, 1), 500, y + 35, f"{axis}_pd_command")
        saturation = diagram.saturation(ACTUATOR_LIMIT_NM, 590, y + 35, f"{axis}_wheel_limit")
        actuator_error = diagram.summation((1, -1), 680, y + 35, f"{axis}_wheel_error")
        actuator_gain = diagram.gain(
            1.0 / ACTUATOR_TIME_CONSTANT_SECONDS,
            755,
            y + 35,
            f"{axis}_wheel_bandwidth",
        )
        actuator = diagram.integrator(0.0, 835, y + 35, f"{axis}_wheel_torque")
        actuator_split = diagram.split(915, y + 50, f"{axis}_wheel_torque_split")
        disturbance_split = diagram.split(640, y + 285, f"{axis}_disturbance_split")
        net_torque = diagram.summation((1, 1), 985, y + 140, f"{axis}_net_torque")
        inverse_inertia = diagram.gain(
            1.0 / float(parameters["inertia"]),
            1060,
            y + 140,
            f"{axis}_inverse_inertia",
        )
        omega = diagram.integrator(
            math.radians(float(parameters["initial_rate_deg_s"])),
            1140,
            y + 140,
            f"{axis}_body_rate",
        )
        omega_split = diagram.split(1220, y + 155, f"{axis}_body_rate_split")
        theta = diagram.integrator(
            math.radians(float(parameters["initial_angle_deg"])),
            1300,
            y + 140,
            f"{axis}_angle",
        )
        theta_split = diagram.split(1380, y + 155, f"{axis}_angle_split")

        theta_recorder = diagram.recorder(f"theta_{axis}", 1470, y + 110)
        omega_recorder = diagram.recorder(f"omega_{axis}", 1470, y + 200)
        control_recorder = diagram.recorder(f"control_{axis}", 985, y - 25)
        disturbance_recorder = diagram.recorder(f"disturbance_{axis}", 730, y + 260)

        diagram.connect(kp, command_sum, target_port=1)
        diagram.connect(kd, command_sum, target_port=2)
        diagram.connect(command_sum, saturation)
        diagram.connect(saturation, actuator_error, target_port=1)
        diagram.connect(actuator_error, actuator_gain)
        diagram.connect(actuator_gain, actuator)
        diagram.connect(actuator, actuator_split)
        diagram.connect(actuator_split, actuator_error, source_port=1, target_port=2)
        diagram.connect(actuator_split, net_torque, source_port=2, target_port=1)
        diagram.connect(actuator_split, control_recorder, source_port=3)

        diagram.connect(disturbance, disturbance_split)
        diagram.connect(disturbance_split, net_torque, source_port=1, target_port=2)
        diagram.connect(disturbance_split, disturbance_recorder, source_port=2)
        diagram.connect(net_torque, inverse_inertia)
        diagram.connect(inverse_inertia, omega)
        diagram.connect(omega, omega_split)
        diagram.connect(omega_split, kd, source_port=1)
        diagram.connect(omega_split, theta, source_port=2)
        diagram.connect(omega_split, omega_recorder, source_port=3)
        diagram.connect(theta, theta_split)
        diagram.connect(theta_split, kp, source_port=1)
        diagram.connect(theta_split, theta_recorder, source_port=2)

    run_scilab_script(
        diagram.emit(),
        180.0,
        gui=True,
        environment={"XCOS_MCP_MODEL_PATH": str(MODEL_PATH)},
    )


def parse_tool_result(response: Any) -> dict[str, Any]:
    if response.isError:
        detail = response.content[0].text if response.content else "unknown MCP error"
        raise RuntimeError(detail)
    return json.loads(response.content[0].text)


async def run_through_mcp() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xcos_mcp"],
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "XCOS_ALLOWED_MODEL_ROOTS": str(ROOT),
        },
    )
    outputs = [f"{kind}_{axis}" for axis in AXES for kind in ("theta", "omega", "control", "disturbance")]
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            inspection = parse_tool_result(
                await session.call_tool("inspect_xcos_model", {"model_path": str(MODEL_PATH)})
            )
            validation = parse_tool_result(
                await session.call_tool(
                    "validate_xcos_model",
                    {"model_path": str(MODEL_PATH), "timeout_seconds": 180.0},
                )
            )
            simulation = parse_tool_result(
                await session.call_tool(
                    "simulate_xcos_model",
                    {
                        "model_path": str(MODEL_PATH),
                        "duration_seconds": DURATION_SECONDS,
                        "outputs": outputs,
                        "timeout_seconds": 240.0,
                        "max_samples": RETURNED_SAMPLES,
                    },
                )
            )
    return inspection, validation, simulation


def rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def persist_results(
    inspection: dict[str, Any],
    validation: dict[str, Any],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    times = simulation["time"]
    signals = simulation["signals"]
    names = list(signals)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(["time_s", *names])
        writer.writerows(zip(times, *(signals[name] for name in names)))

    settled = [index for index, instant in enumerate(times) if instant >= 600.0]
    metrics: dict[str, Any] = {}
    for axis in AXES:
        theta = signals[f"theta_{axis}"]
        omega = signals[f"omega_{axis}"]
        control = signals[f"control_{axis}"]
        disturbance = signals[f"disturbance_{axis}"]
        metrics[axis] = {
            "initial_angle_deg": math.degrees(theta[0]),
            "final_angle_deg": math.degrees(theta[-1]),
            "peak_absolute_angle_deg": math.degrees(max(abs(value) for value in theta)),
            "rms_angle_after_600s_deg": math.degrees(rms([theta[index] for index in settled])),
            "peak_body_rate_deg_s": math.degrees(max(abs(value) for value in omega)),
            "peak_control_torque_Nm": max(abs(value) for value in control),
            "peak_disturbance_torque_Nm": max(abs(value) for value in disturbance),
        }
    summary = {
        "engine": simulation["engine"],
        "mcp_tools_used": ["inspect_xcos_model", "validate_xcos_model", "simulate_xcos_model"],
        "model_imported": validation["imported"],
        "duration_seconds": simulation["duration_seconds"],
        "sample_period_seconds": SAMPLE_PERIOD_SECONDS,
        "returned_sample_count": len(times),
        "original_sample_counts": simulation["original_sample_counts"],
        "block_count": len(inspection["blocks"]),
        "link_count": len(inspection["links"]),
        "assumptions": {
            "orbit": "circular 500 km representative orbital rate",
            "dynamics": "uncoupled small-angle rigid-body axes",
            "actuator": "reaction-wheel torque limit with first-order lag",
            "disturbances": [name for name, *_ in DISTURBANCES] + ["constant_bias"],
        },
        "axes": AXES,
        "metrics": metrics,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_svg(times, signals)
    return summary


def polyline(
    values: list[float],
    times: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    limit: float,
) -> str:
    points = []
    stride = max(1, math.ceil(len(times) / 2_000))
    selected = list(range(0, len(times), stride))
    if selected[-1] != len(times) - 1:
        selected.append(len(times) - 1)
    for index in selected:
        instant, value = times[index], values[index]
        px = x + width * instant / times[-1]
        py = y + height * (0.5 - value / (2.0 * limit))
        points.append(f"{px:.2f},{py:.2f}")
    return " ".join(points)


def write_svg(times: list[float], signals: dict[str, list[float]]) -> None:
    width, height = 1200, 760
    colors = {"roll": "#58a6ff", "pitch": "#f0883e", "yaw": "#a371f7"}
    panels = (
        ("Attitude error", "theta", math.radians(8.5), "deg"),
        ("Reaction-wheel control torque", "control", ACTUATOR_LIMIT_NM * 1.05, "N m"),
        ("Environmental disturbance torque", "disturbance", 45e-6, "N m"),
    )
    body = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
        '<text x="70" y="42" fill="#f0f6fc" font-family="sans-serif" '
        'font-size="24">Three-axis spacecraft attitude simulation</text>',
        '<text x="70" y="66" fill="#8b949e" font-family="sans-serif" '
        'font-size="13">12,000 s native Scilab/Xcos run via xcos-mcp</text>',
    ]
    for panel_index, (title, prefix, limit, unit) in enumerate(panels):
        x, y, panel_width, panel_height = 75, 100 + panel_index * 210, 1070, 160
        body.extend(
            [
                f'<rect x="{x}" y="{y}" width="{panel_width}" height="{panel_height}" '
                'fill="#161b22" stroke="#30363d"/>',
                f'<line x1="{x}" y1="{y + panel_height / 2}" '
                f'x2="{x + panel_width}" y2="{y + panel_height / 2}" stroke="#484f58"/>',
                f'<text x="{x}" y="{y - 10}" fill="#c9d1d9" font-family="sans-serif" '
                f'font-size="15">{title} ({unit})</text>',
            ]
        )
        for axis in AXES:
            values = signals[f"{prefix}_{axis}"]
            plotted = [math.degrees(value) for value in values] if prefix == "theta" else values
            plotted_limit = math.degrees(limit) if prefix == "theta" else limit
            body.append(
                f'<polyline points="{polyline(plotted, times, x, y, panel_width, panel_height, plotted_limit)}" '
                f'fill="none" stroke="{colors[axis]}" stroke-width="1.4"/>'
            )
    legend_x = 865
    for index, axis in enumerate(AXES):
        body.append(
            f'<text x="{legend_x + index * 90}" y="42" fill="{colors[axis]}" '
            f'font-family="sans-serif" font-size="14">{axis}</text>'
        )
    body.append('<text x="520" y="735" fill="#8b949e" font-family="sans-serif" font-size="13">Time (s)</text>')
    body.append("</svg>")
    PLOT_PATH.write_text("\n".join(body) + "\n", encoding="utf-8")


def main() -> None:
    build_model()
    inspection, validation, simulation = asyncio.run(run_through_mcp())
    summary = persist_results(inspection, validation, simulation)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
