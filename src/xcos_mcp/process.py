# SPDX-License-Identifier: GPL-3.0-only
"""Bounded subprocess access to the locally installed Scilab/Xcos runtime."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class ScilabExecutionError(RuntimeError):
    """Raised when Scilab cannot start or reports a failed operation."""


@dataclass(frozen=True)
class ScilabResult:
    executable: str
    command: tuple[str, ...]
    output: str


def _executable_candidates(gui: bool) -> list[str | Path | None]:
    name = "scilab" if gui else "scilab-cli"
    env_names = ("SCILAB_GUI_BIN", "SCILAB_BIN") if gui else ("SCILAB_CLI_BIN",)
    candidates: list[str | Path | None] = [os.environ.get(item) for item in env_names]
    candidates.append(shutil.which(name))
    candidates.extend(sorted(Path("/opt").glob(f"scilab*/bin/{name}"), reverse=True))
    return candidates


def resolve_scilab(gui: bool = True) -> Path | None:
    for candidate in _executable_candidates(gui):
        if candidate:
            path = Path(candidate).expanduser().resolve()
            if path.is_file() and os.access(path, os.X_OK):
                return path
    return None


def scilab_root() -> Path | None:
    executable = resolve_scilab(gui=True) or resolve_scilab(gui=False)
    return executable.parent.parent if executable else None


def scilab_string(value: str | Path) -> str:
    """Quote trusted internal text using Scilab's doubled-quote convention."""
    return str(value).replace('"', '""')


def validate_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive finite number")
    return float(timeout_seconds)


def wait_for_files(paths: list[Path], timeout_seconds: float = 10.0) -> bool:
    """Wait until asynchronous Xcos exports exist with stable, non-zero sizes."""
    deadline = time.monotonic() + validate_timeout(timeout_seconds)
    previous: tuple[int, ...] | None = None
    stable_observations = 0
    while time.monotonic() < deadline:
        if all(path.is_file() and path.stat().st_size > 0 for path in paths):
            sizes = tuple(path.stat().st_size for path in paths)
            stable_observations = stable_observations + 1 if sizes == previous else 0
            if stable_observations >= 2:
                return True
            previous = sizes
        time.sleep(0.05)
    return False


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_scilab_script(
    script: str,
    timeout_seconds: float = 120.0,
    *,
    gui: bool = True,
    environment: dict[str, str] | None = None,
) -> ScilabResult:
    timeout = validate_timeout(timeout_seconds)
    executable = resolve_scilab(gui=gui)
    if executable is None:
        variable = "SCILAB_GUI_BIN" if gui else "SCILAB_CLI_BIN"
        raise ScilabExecutionError(f"Scilab executable not found; set {variable}.")

    prefix: list[str] = []
    if gui and sys.platform.startswith("linux"):
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            raise ScilabExecutionError("xvfb-run is required for headless native Xcos on Linux.")
        prefix = [xvfb, "-a"]

    with tempfile.TemporaryDirectory(prefix="xcos-mcp-") as directory:
        script_path = Path(directory) / "operation.sce"
        error_path = Path(directory) / "error.txt"
        guarded_script = f'''try
{script}
catch
    mputl(lasterror(), "{scilab_string(error_path)}");
    exit(1);
end
'''
        script_path.write_text(guarded_script, encoding="utf-8")
        command = [*prefix, str(executable), "-nb", "-f", str(script_path)]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={
                **os.environ,
                **(environment or {}),
                "LC_ALL": "C",
                "LANG": "C",
                "LANGUAGE": "C",
            },
            start_new_session=os.name != "nt",
        )
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_tree(process)
            output, _ = process.communicate()
            raise TimeoutError(f"Scilab timed out after {timeout:g} seconds. Output: {output[-2000:]}") from exc

        engine_error = error_path.read_text(encoding="utf-8", errors="replace") if error_path.is_file() else ""

    if process.returncode != 0 or engine_error:
        detail = engine_error or output[-4000:]
        raise ScilabExecutionError(f"Scilab exited with {process.returncode}. Error: {detail}")
    return ScilabResult(str(executable), tuple(command), output)


def runtime_info() -> dict[str, object]:
    gui = resolve_scilab(gui=True)
    cli = resolve_scilab(gui=False)
    xvfb = shutil.which("xvfb-run")
    display_ready = not sys.platform.startswith("linux") or bool(xvfb)
    version = None
    error = None
    if cli:
        script = 'mprintf("__XCOS_VERSION__=%s\\n", getversion()); exit(0);'
        try:
            result = run_scilab_script(script, 20.0, gui=False)
            version = next(
                (line.partition("=")[2].strip() for line in result.output.splitlines() if line.startswith("__XCOS_VERSION__=")),
                None,
            )
        except Exception as exc:  # Runtime diagnostics must be returned, not crash the MCP.
            error = str(exc)
    return {
        "accessible": bool(gui and display_ready),
        "scilab_accessible": bool(gui or cli),
        "scilab_gui": str(gui) if gui else None,
        "scilab_cli": str(cli) if cli else None,
        "scilab_root": str(scilab_root()) if scilab_root() else None,
        "version": version,
        "xvfb_run": xvfb,
        "version_error": error,
    }
