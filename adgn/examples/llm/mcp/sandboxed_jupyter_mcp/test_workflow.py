import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from mcp_helpers import read_line_json as _real_read, send_line_json as _real_send
import pytest
import yaml

# Constants for readability in comparisons and timing
STARTUP_DRAIN_SECS = 5.0
INIT_ID = 1
TOOLS_LIST_ID = 99
EXEC_OK_ID = 2
EXEC_NET_ID = 4
EXEC_DENIED_ID = 3


def _send_line_json(w, obj: dict) -> None:
    _real_send(w, obj)


def _read_line_json(r, timeout: float) -> dict | None:
    return _real_read(r, timeout)


@pytest.mark.macos
def test_example_bundle_and_launch(tmp_path):
    # Preconditions: we need jupyter and jupyter-mcp-server resolvable on PATH (hard fail if missing)
    assert shutil.which("jupyter"), "'jupyter' must be on PATH for tests"
    assert shutil.which("jupyter-mcp-server"), (
        "'jupyter-mcp-server' must be on PATH for tests"
    )

    # Ensure our package is importable to subprocesses via PYTHONPATH
    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{src_dir}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_dir)
    )
    env["JUPYTER_LOG_LEVEL"] = "DEBUG"

    bundle_dir = tmp_path / "bundle"
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "workspace").mkdir(parents=True, exist_ok=True)
    sys.stderr.write(f"[test] runtime_dir={runtime_dir.as_posix()}\n")

    venv_root = Path(sys.executable).resolve().parents[1]  # <venv>/bin/.. -> venv root
    composer_cfg = {
        "version": 1,
        "bundle_dir": bundle_dir.as_posix(),
        "runtime_dir": runtime_dir.as_posix(),
        "kernel": {
            "name": "python3",
            "display_name": "Python 3 (sandboxed)",
            "language": "python",
            "argv_base": [sys.executable, "-m", "ipykernel_launcher"],
        },
        "policy": {
            "env": {
                "set": {
                    "JUPYTER_RUNTIME_DIR": f"{runtime_dir.as_posix()}/runtime",
                    "JUPYTER_DATA_DIR": f"{bundle_dir.as_posix()}/data",
                    "JUPYTER_CONFIG_DIR": f"{bundle_dir.as_posix()}/config",
                    "JUPYTER_PATH": f"{bundle_dir.as_posix()}/data",
                    "PYTHONPYCACHEPREFIX": f"{runtime_dir.as_posix()}/pycache",
                    "MPLCONFIGDIR": f"{runtime_dir.as_posix()}/mpl",
                    "HOME": runtime_dir.as_posix(),
                },
                "passthrough": [],
            },
            "fs": {
                # Limit read to python binary dir and stdlib site-packages only
                "read_paths": [
                    venv_root.as_posix(),
                    (venv_root / "lib").as_posix(),
                    bundle_dir.as_posix(),
                ],
                "write_paths": [
                    runtime_dir.as_posix(),
                    (runtime_dir / "workspace").as_posix(),
                ],
            },
            "net": {"mode": "loopback"},
            "platform": {"seatbelt": {"trace": False}},
        },
    }
    composer_yaml = yaml.safe_dump(composer_cfg, sort_keys=False)

    # Run composer via stdin
    subprocess.run(
        [
            sys.executable,
            "-m",
            "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_sandbox_compose",
            "--config",
            "-",
        ],
        input=composer_yaml.encode(),
        check=True,
        env=env,
    )

    # Launch the MCP stdio bridge and Jupyter using the generated bundle
    config_dir = bundle_dir / "config"
    kernels_dir = bundle_dir / "kernels"

    assert (config_dir / "jupyter_server_config.py").exists()
    assert (kernels_dir / "python3" / "kernel.json").exists()

    launch_cmd = [
        sys.executable,
        "-m",
        "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_mcp_launch",
        "--config",
        str(config_dir),
        "--kernels",
        str(kernels_dir),
        "--workspace",
        str(runtime_dir / "workspace"),
        "--kernel-name",
        "python3",
        "--port",
        "0",
        "--token",
        "auto",
        "--start-new-runtime",
        "--log-dir",
        str(runtime_dir),
    ]

    p = subprocess.Popen(
        launch_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Allow some startup logs to flow, helps MCP readiness
    start = time.time()
    while time.time() - start < STARTUP_DRAIN_SECS:
        line = p.stderr.readline()
        if not line:
            break
        sys.stderr.write("[stderr] " + line.decode(errors="ignore"))

    # MCP stdio protocol: initialize, then execute a code cell
    try:
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": INIT_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "pytest", "version": "0.0.1"},
                },
            },
        )
        init_resp = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not init_resp:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == INIT_ID and ("result" in m or "error" in m):
                init_resp = m
        assert init_resp is not None, f"initialize failed: {init_resp}"
        assert "result" in init_resp, f"initialize failed: {init_resp}"
        _send_line_json(
            p.stdin,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        time.sleep(0.3)
        # List available tools (sanity)
        _send_line_json(
            p.stdin, {"jsonrpc": "2.0", "id": TOOLS_LIST_ID, "method": "tools/list"}
        )
        tools_resp = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not tools_resp:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == TOOLS_LIST_ID and ("result" in m or "error" in m):
                tools_resp = m
        assert tools_resp is not None, f"tools/list failed: {tools_resp}"
        assert "result" in tools_resp, f"tools/list failed: {tools_resp}"

        # Happy-path execution
        code_ok = "print('OK:', 2+2)"
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": EXEC_OK_ID,
                "method": "tools/call",
                "params": {
                    "name": "append_execute_code_cell",
                    "arguments": {"cell_source": code_ok},
                },
            },
        )
        exec_ok = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not exec_ok:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == EXEC_OK_ID and ("result" in m or "error" in m):
                exec_ok = m
        assert exec_ok is not None, f"code exec failed: {exec_ok}"
        assert "result" in exec_ok, f"code exec failed: {exec_ok}"

        # Network should not work in loopback mode: external HTTP should fail
        code_net = (
            "import urllib.request\n"
            "try:\n"
            "    with urllib.request.urlopen('http://example.com', timeout=6) as r:\n"
            "        data = r.read(100).decode('utf-8', 'ignore')\n"
            "    print('NET_OK:', 'Example Domain' in data)\n"
            "except Exception as e:\n"
            "    print('NET_FAIL:', type(e).__name__, str(e)[:80])\n"
        )
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": EXEC_NET_ID,
                "method": "tools/call",
                "params": {
                    "name": "append_execute_code_cell",
                    "arguments": {"cell_source": code_net},
                },
            },
        )
        exec_net = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not exec_net:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == EXEC_NET_ID and ("result" in m or "error" in m):
                exec_net = m
        assert exec_net is not None, f"no network response: {exec_net}"
        assert ("result" in exec_net) or ("error" in exec_net), (
            f"no network response: {exec_net}"
        )
        blob_net = json.dumps(exec_net)
        assert (
            ("NET_FAIL:" in blob_net)
            or ("Error" in blob_net)
            or ("timed out" in blob_net)
            or ("Name or service not known" in blob_net)
            or ("Network is unreachable" in blob_net)
        ), blob_net

        # Sandbox boundary: attempt to write outside runtime_dir should fail
        outside_file = (
            tmp_path.parent / (tmp_path.name + "_outside") / "denied.txt"
        ).as_posix()
        code_denied = f"import pathlib\npathlib.Path('{outside_file}').write_text('x')"
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": EXEC_DENIED_ID,
                "method": "tools/call",
                "params": {
                    "name": "append_execute_code_cell",
                    "arguments": {"cell_source": code_denied},
                },
            },
        )
        exec_bad = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not exec_bad:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == EXEC_DENIED_ID and ("result" in m or "error" in m):
                exec_bad = m
        # Expect denial reflected as an error or failure text in results
        assert exec_bad is not None, f"no response for denied write: {exec_bad}"
        assert ("error" in exec_bad) or ("result" in exec_bad), (
            f"no response for denied write: {exec_bad}"
        )
        blob = json.dumps(exec_bad)
        assert (
            ("Permission" in blob)
            or ("Operation not permitted" in blob)
            or ("Errno" in blob)
            or ("Connection was lost" in blob)
        ), blob
    finally:
        with contextlib.suppress(Exception):
            p.terminate()


@pytest.mark.macos
def test_network_open_allows_http(tmp_path):
    assert shutil.which("jupyter")
    assert shutil.which("jupyter-mcp-server")
    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{src_dir}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_dir)
    )

    bundle_dir = tmp_path / "bundle"
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "workspace").mkdir(parents=True, exist_ok=True)

    venv_root = Path(sys.executable).resolve().parents[1]
    composer_cfg = {
        "version": 1,
        "bundle_dir": bundle_dir.as_posix(),
        "runtime_dir": runtime_dir.as_posix(),
        "kernel": {
            "name": "python3",
            "display_name": "Python 3 (sandboxed)",
            "language": "python",
            "argv_base": [sys.executable, "-m", "ipykernel_launcher"],
        },
        "policy": {
            "env": {"set": {"HOME": runtime_dir.as_posix()}, "passthrough": []},
            "fs": {
                "read_paths": [
                    venv_root.as_posix(),
                    (venv_root / "lib").as_posix(),
                    bundle_dir.as_posix(),
                    "/System/Library",
                    "/usr/lib",
                ],
                "write_paths": [
                    runtime_dir.as_posix(),
                    (runtime_dir / "workspace").as_posix(),
                ],
            },
            "net": {"mode": "open"},
            "platform": {"seatbelt": {"trace": False}},
        },
    }
    composer_yaml = yaml.safe_dump(composer_cfg, sort_keys=False)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_sandbox_compose",
            "--config",
            "-",
        ],
        input=composer_yaml.encode(),
        check=True,
        env=env,
    )

    config_dir = bundle_dir / "config"
    kernels_dir = bundle_dir / "kernels"
    p = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_mcp_launch",
            "--config",
            str(config_dir),
            "--kernels",
            str(kernels_dir),
            "--workspace",
            str(runtime_dir / "workspace"),
            "--kernel-name",
            "python3",
            "--port",
            "0",
            "--token",
            "auto",
            "--start-new-runtime",
            "--log-dir",
            str(runtime_dir),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Drain a bit of stderr for readiness
    start = time.time()
    while time.time() - start < STARTUP_DRAIN_SECS:
        line = p.stderr.readline()
        if not line:
            break
        sys.stderr.write("[stderr] " + line.decode(errors="ignore"))

    try:
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": INIT_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "pytest", "version": "0.0.1"},
                },
            },
        )
        init = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not init:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == INIT_ID and ("result" in m or "error" in m):
                init = m
        assert init is not None, init
        assert "result" in init, init
        _send_line_json(
            p.stdin,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        time.sleep(0.3)

        # Plain HTTP to avoid TLS CA access inside sandbox
        code_net = (
            "import urllib.request\n"
            "with urllib.request.urlopen('http://example.com', timeout=8) as r:\n"
            "    data = r.read(200).decode('utf-8', 'ignore')\n"
            "print('NET_OK:', 'Example Domain' in data, len(data))\n"
        )
        _send_line_json(
            p.stdin,
            {
                "jsonrpc": "2.0",
                "id": EXEC_OK_ID,
                "method": "tools/call",
                "params": {
                    "name": "append_execute_code_cell",
                    "arguments": {"cell_source": code_net},
                },
            },
        )
        resp = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not resp:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == EXEC_OK_ID and ("result" in m or "error" in m):
                resp = m
        assert resp is not None, resp
        assert "result" in resp, resp
        blob = json.dumps(resp)
        assert ("NET_OK:" in blob) or ("Example Domain" in blob), blob
    finally:
        with contextlib.suppress(Exception):
            p.terminate()
