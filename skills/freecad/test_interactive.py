"""Integration test for the interactive FreeCAD RPC workflow.

Starts FreeCAD with the neka-nat/freecad-mcp addon under Xvfb, verifies that
the XML-RPC server starts and responds to ping, execute_code, and screenshot
requests.
"""

import base64
import json
import os
import signal
import subprocess
import time
import xmlrpc.client

import pytest
import pytest_bazel

from util.bazel.runfiles import get_required_path

_FREECAD_APPIMAGE_RLOCATION = "freecad_appimage/file/FreeCAD.AppImage"
_FREECAD_MCP_ADDON_RLOCATION = "freecad_mcp/addon/FreeCADMCP"
_RPC_PORT = 9875
_RPC_URL = f"http://localhost:{_RPC_PORT}"


@pytest.fixture(scope="module")
def freecad_rpc(xvfb_display, tmp_path_factory):
    """Start FreeCAD with the MCP addon and yield an XML-RPC proxy."""
    appimage = get_required_path(_FREECAD_APPIMAGE_RLOCATION)
    addon_dir = get_required_path(_FREECAD_MCP_ADDON_RLOCATION)

    fc_home = tmp_path_factory.mktemp("freecad_rpc_home")
    (fc_home / ".local" / "share" / "FreeCAD" / "1.0").mkdir(parents=True)

    # Enable auto-start of the RPC server.
    # getUserAppDataDir() returns $FREECAD_USER_HOME/ directly.
    settings = {"auto_start_rpc": True, "remote_enabled": False}
    (fc_home / "freecad_mcp_settings.json").write_text(json.dumps(settings))

    env = {
        **os.environ,
        "DISPLAY": xvfb_display,
        "HOME": str(fc_home),
        "FREECAD_USER_HOME": str(fc_home),
        "QT_QPA_PLATFORM": "xcb",
    }
    # Remove Wayland vars to force X11.
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("GDK_BACKEND", None)

    # -M loads the addon without symlinking into Mod/.
    # The addon_dir points to the FreeCADMCP directory; -M needs its parent.
    proc = subprocess.Popen(
        [str(appimage), "freecad", "-M", str(addon_dir)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )

    proxy = xmlrpc.client.ServerProxy(_RPC_URL, allow_none=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            proxy.ping()
            break
        except Exception:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                raise RuntimeError(f"FreeCAD exited early (rc={proc.returncode}): {stderr}")
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("FreeCAD RPC server did not start within 30s")

    yield proxy

    # Shutdown: send SIGTERM, then force-kill after timeout.
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def test_ping(freecad_rpc):
    assert freecad_rpc.ping() is True


def test_execute_code(freecad_rpc):
    result = freecad_rpc.execute_code("""
import FreeCAD
import Part
doc = FreeCAD.newDocument("RpcTest")
box = doc.addObject("Part::Box", "TestBox")
box.Length = 42
box.Width = 21
box.Height = 10
doc.recompute()
print(f"box volume: {box.Shape.Volume:.1f}")
""")
    assert result["success"] is True
    assert "box volume: 8820.0" in result["message"]


def test_list_documents(freecad_rpc):
    docs = freecad_rpc.list_documents()
    assert "RpcTest" in docs


def test_screenshot(freecad_rpc):
    img_b64 = freecad_rpc.get_active_screenshot("Isometric", 400, 300, "")
    assert img_b64 is not None
    data = base64.b64decode(img_b64)
    # PNG magic bytes
    assert data[:4] == b"\x89PNG"
    assert len(data) > 100


def test_state_persists(freecad_rpc):
    """Variables from previous execute_code calls persist in the namespace."""
    result = freecad_rpc.execute_code("""
import FreeCAD
doc = FreeCAD.getDocument("RpcTest")
box = doc.getObject("TestBox")
print(f"length: {box.Length}")
""")
    assert result["success"] is True
    assert "length: 42" in result["message"]


def test_error_handling(freecad_rpc):
    """Errors in execute_code are returned, not crash FreeCAD."""
    result = freecad_rpc.execute_code("raise ValueError('test error')")
    assert result["success"] is False
    assert "test error" in result["error"]
    # FreeCAD should still be alive after the error.
    assert freecad_rpc.ping() is True


if __name__ == "__main__":
    pytest_bazel.main()
