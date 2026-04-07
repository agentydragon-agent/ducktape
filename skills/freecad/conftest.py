"""Shared fixtures for FreeCAD tests."""

import os
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
import pytest_bazel
from opentelemetry import trace

from util.bazel.runfiles import get_required_path
from util.oci import OciImage
from util.testing.otel_tracing import configure_tracing, export_traces

# Docker-based test image (used by test_container_primitives.py)
FREECAD_TEST = OciImage("_main/skills/freecad/freecad_test.rloc", "freecad-test:pinned")

# AppImage-based test fixtures
# http_file repos place downloaded files under a "file/" subdirectory
_FREECAD_APPIMAGE_RLOCATION = "freecad_appimage/file/FreeCAD.AppImage"

tracer = trace.get_tracer(__name__)


def pytest_configure(config: pytest.Config) -> None:
    configure_tracing(config)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    export_traces(session.config)


@pytest.fixture(scope="session")
def freecad_appimage_path() -> Path:
    """Resolve the FreeCAD AppImage from Bazel runfiles."""
    return get_required_path(_FREECAD_APPIMAGE_RLOCATION)


@pytest.fixture(scope="session")
def freecad_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Hermetic FreeCAD user home dir shared across the test session.

    Prevents the FreeCAD version-migration dialog from blocking headless runs
    by giving every FreeCAD invocation a clean, private HOME and FREECAD_USER_HOME.
    All fixtures that launch FreeCAD inject both env vars from this path.
    """
    return tmp_path_factory.mktemp("freecad_home")


@pytest.fixture(scope="session")
def xvfb_display() -> Generator[str]:
    """Start a session-scoped Xvfb server. Yields the DISPLAY string (e.g. ':1').

    Uses Xvfb -displayfd to obtain a dynamically allocated display number,
    avoiding collisions when tests run concurrently on the same worker.
    Fails immediately if Xvfb exits right after start.
    """
    r_fd, w_fd = os.pipe()
    proc = subprocess.Popen(
        ["Xvfb", "-displayfd", str(w_fd), "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(w_fd,),
    )
    os.close(w_fd)
    # -displayfd writes the allocated display number (e.g. "1\n") once ready
    raw = os.read(r_fd, 16).decode().strip()
    os.close(r_fd)
    if proc.poll() is not None:
        raise RuntimeError(f"Xvfb exited immediately (returncode={proc.returncode})")
    display = f":{raw}"
    yield display
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def freecad_gui(freecad_appimage_path: Path, xvfb_display: str, freecad_home: Path):
    """Run a FreeCAD script under the GUI binary with a real Xvfb display.

    Requires Xvfb (provided by the xvfb_display session fixture). Use this for
    scripts that need OpenGL/Coin3D 3D rendering or TechDraw HLR.

    Scripts must use the QTimer.singleShot(0, ...) + run_gui_script() pattern to
    defer work until after QApplication::exec() starts, and must NOT call os._exit().

    Usage: result = freecad_gui(script, outdir=Path(...), env={...})
    """

    def _run(script: Path, outdir: Path, env: dict | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
        run_env = {
            **os.environ,
            "DISPLAY": xvfb_display,
            "OUTDIR": str(outdir),
            "HOME": str(freecad_home),
            "FREECAD_USER_HOME": str(freecad_home),
        }
        if env:
            run_env.update(env)
        return subprocess.run(
            [freecad_appimage_path, "freecad", script],
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run


def assert_run_ok(result: subprocess.CompletedProcess, script_name: str, uo: Path, name: str) -> None:
    """Assert subprocess success, saving stdout/stderr to undeclared outputs for post-mortem."""
    if result.stdout:
        (uo / f"{name}.stdout").write_text(result.stdout)
    if result.stderr:
        (uo / f"{name}.stderr").write_text(result.stderr)
    assert result.returncode == 0, (
        f"{script_name} failed (exit {result.returncode}) — see {name}.stdout/.stderr in test outputs"
    )


@pytest.fixture(scope="session")
def freecad_run(freecad_appimage_path: Path, freecad_home: Path):
    """Run a FreeCAD script headlessly (no xvfb) via freecadcmd. Returns a callable.

    Suitable for scripts that only use Part geometry and importDXF — no TechDraw HLR.
    Uses QT_QPA_PLATFORM=offscreen; no Xvfb required.

    Usage: result = freecad_run(script, outdir=Path(...))
    """

    def _run(script: Path, outdir: Path, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        run_env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "OUTDIR": str(outdir),
            "HOME": str(freecad_home),
            "FREECAD_USER_HOME": str(freecad_home),
        }
        if env:
            run_env.update(env)
        return subprocess.run(
            [freecad_appimage_path, "freecadcmd", script],
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run


if __name__ == "__main__":
    pytest_bazel.main()
