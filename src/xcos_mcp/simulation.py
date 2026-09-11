# SPDX-License-Identifier: GPL-3.0-only
"""Real numerical simulation through native Scilab/Xcos."""

from __future__ import annotations

import csv
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid

from .async_utils import run_blocking
from .config import artifact_dir
from .model import parse_xcos, recorded_outputs
from .process import run_scilab_script, validate_timeout, wait_for_files


DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_OUTPUTS = 64
MAX_RETURNED_SAMPLES = 100_000


def _validate_duration(duration: float) -> float:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration_seconds must be a positive finite number")
    return float(duration)


def _signal_names(outputs: list[str]) -> list[str]:
    import re

    if not isinstance(outputs, list) or not outputs:
        raise ValueError("outputs must contain at least one TOWS_c variable name")
    if len(outputs) > MAX_OUTPUTS:
        raise ValueError(f"outputs cannot contain more than {MAX_OUTPUTS} names")
    pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,18}$")
    unique: list[str] = []
    for name in outputs:
        if not isinstance(name, str) or not pattern.fullmatch(name):
            raise ValueError("output names must be Scilab identifiers of at most 19 characters")
        if name not in unique:
            unique.append(name)
    return unique


def _read_series(path: Path) -> tuple[list[float], list[float]]:
    times: list[float] = []
    values: list[float] = []
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.reader(source):
            if len(row) >= 2:
                times.append(float(row[0]))
                values.append(float(row[1]))
    if not times:
        raise RuntimeError(f"Xcos produced no numerical samples in {path.name}")
    return times, values


def _downsample(times: list[float], values: list[float], maximum: int) -> tuple[list[float], list[float]]:
    if len(times) <= maximum:
        return times, values
    indices = sorted({round(index * (len(times) - 1) / (maximum - 1)) for index in range(maximum)})
    return [times[index] for index in indices], [values[index] for index in indices]


def _validate_max_samples(maximum: int) -> int:
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not 2 <= maximum <= MAX_RETURNED_SAMPLES
    ):
        raise ValueError(f"max_samples must be an integer between 2 and {MAX_RETURNED_SAMPLES}")
    return maximum


def _times_equal(left: list[float], right: list[float]) -> bool:
    return len(left) == len(right) and all(
        math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12) for a, b in zip(left, right)
    )


def simulate_model(
    model_path: str,
    duration_seconds: float,
    outputs: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_samples: int = 10_000,
) -> dict[str, Any]:
    """Import and simulate a saved model, returning each requested TOWS_c series."""
    duration = _validate_duration(duration_seconds)
    timeout = validate_timeout(timeout_seconds)
    max_samples = _validate_max_samples(max_samples)
    path, root = parse_xcos(model_path)
    names = _signal_names(outputs)
    available = recorded_outputs(root)
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f"Requested outputs are not configured by TOWS_c: {missing}; available: {available}")

    with tempfile.TemporaryDirectory(prefix="xcos-mcp-simulation-") as directory:
        temporary = Path(directory)
        csv_paths = {name: temporary / f"{name}.csv" for name in names}
        writes = "\n".join(
            f'csvWrite([{name}.time {name}.values], getenv("XCOS_MCP_OUTPUT_{index}"), ",");'
            for index, name in enumerate(names)
        )
        script = f'''mode(-1);
lines(0);
loadXcosLibs();
loadScicos();
scs_m = xcosDiagramToScilab(getenv("XCOS_MCP_MODEL_PATH"));
scs_m.props.tf = {duration:.17g};
scicos_simulate(scs_m, list());
{writes}
exit(0);
'''
        environment = {"XCOS_MCP_MODEL_PATH": str(path)}
        environment.update({
            f"XCOS_MCP_OUTPUT_{index}": str(csv_paths[name])
            for index, name in enumerate(names)
        })
        result = run_scilab_script(script, timeout, gui=True, environment=environment)
        if not wait_for_files(list(csv_paths.values())):
            raise RuntimeError(f"Scilab returned without producing simulation output: {result.output[-2000:]}")

        series: dict[str, dict[str, list[float]]] = {}
        original_sample_counts: dict[str, int] = {}
        for name, csv_path in csv_paths.items():
            if not csv_path.is_file():
                raise RuntimeError(f"Xcos did not produce requested TOWS_c signal: {name}")
            times, values = _read_series(csv_path)
            original_sample_counts[name] = len(times)
            times, values = _downsample(times, values, max_samples)
            series[name] = {"time": times, "values": values}

    first_times = series[names[0]]["time"]
    aligned = all(_times_equal(first_times, series[name]["time"]) for name in names[1:])
    response: dict[str, Any] = {
        "success": True,
        "engine": "Scilab/Xcos",
        "model_path": str(path),
        "duration_seconds": duration,
        "available_outputs": available,
        "series": series,
        "aligned": aligned,
        "original_sample_counts": original_sample_counts,
        "downsampled": any(count > max_samples for count in original_sample_counts.values()),
    }
    if aligned:
        response["time"] = first_times
        response["signals"] = {name: series[name]["values"] for name in names}
    return response


def _first_order_script(duration: float) -> str:
    buffer_size = max(2_000, math.ceil(duration * 20) + 100)
    return f'''mode(-1);
lines(0);
loadXcosLibs();
loadScicos();
scs_m = scicos_diagram();
scs_m.props.tf = {duration:.17g};

scs_m.objs(1) = CONST_m("define");
scs_m.objs(1).model.rpar = 1;
scs_m.objs(1).graphics.exprs = "1";
scs_m.objs(1).graphics.orig = [20 100];
scs_m.objs(1).graphics.pout = 7;

scs_m.objs(2) = SUMMATION("define");
scs_m.objs(2).graphics.orig = [100 95];
scs_m.objs(2).graphics.pin = [7; 11];
scs_m.objs(2).graphics.pout = 8;

scs_m.objs(3) = INTEGRAL_m("define");
scs_m.objs(3).graphics.orig = [190 100];
scs_m.objs(3).graphics.pin = 8;
scs_m.objs(3).graphics.pout = 9;

scs_m.objs(4) = SPLIT_f("define");
scs_m.objs(4).graphics.orig = [270 116];
scs_m.objs(4).graphics.pin = 9;
scs_m.objs(4).graphics.pout = [10; 11];

scs_m.objs(5) = TOWS_c("define");
scs_m.objs(5).graphics.orig = [350 80];
scs_m.objs(5).graphics.pin = 10;
scs_m.objs(5).graphics.pein = 12;
scs_m.objs(5).graphics.exprs = ["{buffer_size}"; "first_order_y"; "0"];
scs_m.objs(5).model.ipar = [{buffer_size}; length(ascii("first_order_y")); ascii("first_order_y")'];

scs_m.objs(6) = CLOCK_c("define");
scs_m.objs(6).graphics.orig = [350 180];
scs_m.objs(6).graphics.peout = 12;

scs_m.objs(7) = scicos_link(from=[1 1 0], to=[2 1 1]);
scs_m.objs(8) = scicos_link(from=[2 1 0], to=[3 1 1]);
scs_m.objs(9) = scicos_link(from=[3 1 0], to=[4 1 1]);
scs_m.objs(10) = scicos_link(from=[4 1 0], to=[5 1 1]);
scs_m.objs(11) = scicos_link(from=[4 2 0], to=[2 2 1]);
scs_m.objs(12) = scicos_link(from=[6 1 0], to=[5 1 1], ct=[1 -1]);

xcosDiagramToScilab(getenv("XCOS_MCP_MODEL_PATH"), scs_m);
scicos_simulate(scs_m, list());
csvWrite([first_order_y.time first_order_y.values], getenv("XCOS_MCP_CSV_PATH"), ",");
scf(0); plot(first_order_y.time, first_order_y.values);
xtitle("First-order step response", "Time (s)", "y");
xs2png(0, getenv("XCOS_MCP_PLOT_PATH"));
exit(0);
'''


def simulate_first_order(
    duration_seconds: float = 10.0,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_samples: int = 10_000,
) -> dict[str, Any]:
    """Build and simulate the reference G(s)=1/(s+1) model in real Xcos."""
    duration = _validate_duration(duration_seconds)
    timeout = validate_timeout(timeout_seconds)
    max_samples = _validate_max_samples(max_samples)
    with tempfile.TemporaryDirectory(prefix="xcos-mcp-first-order-") as directory:
        temporary = Path(directory)
        model = temporary / "first_order.xcos"
        csv_path = temporary / "first_order.csv"
        plot = temporary / "first_order.png"
        result = run_scilab_script(
            _first_order_script(duration),
            timeout,
            gui=True,
            environment={
                "XCOS_MCP_MODEL_PATH": str(model),
                "XCOS_MCP_CSV_PATH": str(csv_path),
                "XCOS_MCP_PLOT_PATH": str(plot),
            },
        )
        if not wait_for_files([model, csv_path, plot]):
            raise RuntimeError(f"Xcos did not create all reference artifacts: {result.output[-2000:]}")
        times, values = _read_series(csv_path)
        # TOWS_c records from the first event; the known model has y(0)=0.
        if not times or times[0] > 0:
            times.insert(0, 0.0)
            values.insert(0, 0.0)
        original_count = len(times)
        times, values = _downsample(times, values, max_samples)
        destination = artifact_dir() / "first_order" / uuid.uuid4().hex
        destination.mkdir(parents=True, exist_ok=False)
        persisted = {}
        for source in (model, csv_path, plot):
            target = destination / source.name
            shutil.copy2(source, target)
            persisted[source.suffix.lstrip(".")] = str(target)

    at_one_index = min(range(len(times)), key=lambda index: abs(times[index] - 1.0))
    analytical = 1.0 - math.exp(-1.0)
    return {
        "success": True,
        "engine": "Scilab/Xcos",
        "model": "G(s) = 1 / (s + 1)",
        "duration_seconds": duration,
        "time": times,
        "signals": {"y": values},
        "series": {"y": {"time": times, "values": values}},
        "original_sample_count": original_count,
        "downsampled": original_count > max_samples,
        "metrics": {
            "initial_value": values[0],
            "value_at_1_second": values[at_one_index],
            "analytical_value_at_1_second": analytical,
            "absolute_error_at_1_second": abs(values[at_one_index] - analytical),
            "final_value": values[-1],
        },
        "artifacts": persisted,
    }


def analyze_step_response(
    time: list[float],
    signal: list[float],
    reference: float,
    control: list[float] | None = None,
    saturation_limit: float | None = None,
) -> dict[str, float | None]:
    """Calculate conventional 10–90% rise and 2% settling metrics."""
    if len(time) != len(signal) or len(time) < 2:
        raise ValueError("time and signal must have the same length of at least two")
    numeric = [*time, *signal, reference]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric):
        raise ValueError("time, signal, and reference must contain finite numbers")
    if any(right < left for left, right in zip(time, time[1:])):
        raise ValueError("time must be non-decreasing")
    initial = signal[0]
    span = reference - initial
    direction = 1.0 if span >= 0 else -1.0

    def crossing(fraction: float) -> float | None:
        threshold = initial + fraction * span
        return next((instant for instant, value in zip(time, signal) if direction * (value - threshold) >= 0), None)

    rise_start, rise_end = crossing(0.1), crossing(0.9)
    tolerance = max(0.02 * max(abs(reference), abs(span)), 1e-12)
    outside = [index for index, value in enumerate(signal) if abs(value - reference) > tolerance]
    settling = time[outside[-1] + 1] if outside and outside[-1] + 1 < len(time) else (0.0 if not outside else None)
    peak = max(signal) if direction > 0 else min(signal)
    peak_index = signal.index(peak)
    metrics: dict[str, float | None] = {
        "rise_time": None if rise_start is None or rise_end is None else rise_end - rise_start,
        "settling_time": settling,
        "overshoot_percent": max(0.0, direction * (peak - reference)) / max(abs(span), 1e-12) * 100,
        "steady_state_error": reference - signal[-1],
        "peak_value": peak,
        "peak_time": time[peak_index],
    }
    if control is not None:
        if len(control) != len(time) or any(not math.isfinite(value) for value in control):
            raise ValueError("control must contain one finite value per time sample")
        metrics["maximum_absolute_control_input"] = max(abs(value) for value in control)
        if saturation_limit is not None:
            if not math.isfinite(saturation_limit) or saturation_limit <= 0:
                raise ValueError("saturation_limit must be positive and finite")
            metrics["time_in_saturation"] = sum(
                time[index + 1] - time[index]
                for index in range(len(time) - 1)
                if abs(control[index]) >= saturation_limit * (1 - 1e-9)
            )
    return metrics


async def simulate_model_async(*args, **kwargs) -> dict[str, Any]:
    return await run_blocking(simulate_model, *args, **kwargs)


async def simulate_first_order_async(*args, **kwargs) -> dict[str, Any]:
    return await run_blocking(simulate_first_order, *args, **kwargs)
