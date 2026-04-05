"""Shared helpers for FreeCAD scripts running inside the test container.

Mounted into Docker containers as a plain file alongside the FreeCAD scripts.
Uses only stdlib + FreeCAD's bundled Python (no Bazel workspace imports).
"""

import sys
import time

_t0 = time.monotonic()


def log(msg):
    """Print a timestamped message to stderr."""
    print(f"[{time.monotonic() - _t0:.3f}] {msg}", file=sys.stderr, flush=True)


def init_gui():
    """Initialize FreeCAD GUI mode. Call after Gui.showMainWindow(). Returns qapp."""
    try:
        from PySide6 import QtWidgets  # noqa: PLC0415 — FreeCAD version-dependent
    except ImportError:
        from PySide2 import QtWidgets  # noqa: PLC0415
    return QtWidgets.QApplication.instance()


def pump(qapp, seconds=3):
    """Process Qt events for a fixed duration."""
    t0 = time.monotonic()
    for _ in range(int(seconds * 10)):
        if qapp:
            qapp.processEvents()
        time.sleep(0.1)
    log(f"pump({seconds}) done in {time.monotonic() - t0:.2f}s")


def wait_for_view(view, qapp, timeout=15.0, poll_interval=0.05):
    """Poll until TechDraw view has visible edges, processing Qt events."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if qapp:
            qapp.processEvents()
        edges = view.getVisibleEdges()
        if len(edges) > 0:
            elapsed = time.monotonic() - t0
            log(f"TechDraw view ready: {len(edges)} edges after {elapsed:.2f}s")
            return
        time.sleep(poll_interval)
    raise TimeoutError(f"TechDraw view not ready after {timeout}s")
