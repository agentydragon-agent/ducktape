import json
import os
import sys
import shutil
import subprocess
import time
from pathlib import Path
import pytest
import ipykernel  # test-only hard dependency

def _send_line_json(w, obj: dict) -> None:
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def _read_line_json(r, timeout: float) -> dict | None:
    fd = r.fileno()
    os.set_blocking(fd, False)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            b = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        if not b:
            time.sleep(0.02)
            continue
        if b == b"\n":
            break
        buf.extend(b)
    if not buf:
        return None
    try:
        return json.loads(bytes(buf).decode("utf-8", errors="ignore").rstrip("\r"))
    except Exception:
        return None


@pytest.mark.macos
def test_example_bundle_and_launch(tmp_path):
    # Preconditions: we need jupyter and jupyter-mcp-server resolvable on PATH (hard fail if missing)
    assert shutil.which("jupyter"), "'jupyter' must be on PATH for tests"
    assert shutil.which("jupyter-mcp-server"), "'jupyter-mcp-server' must be on PATH for tests"

    # Ensure our package is importable to subprocesses via PYTHONPATH
    src_dir = Path(__file__).resolve().parents[2] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = (f"{src_dir}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_dir))

    bundle_dir = tmp_path / "bundle"
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "workspace").mkdir(parents=True, exist_ok=True)

    composer_yaml = f"""
version: 1
bundle_dir: {bundle_dir.as_posix()}
runtime_dir: {runtime_dir.as_posix()}

kernel:
  name: python3
  display_name: Python 3 (sandboxed)
  language: python
  argv_base:
    - {sys.executable}
    - -m
    - ipykernel_launcher

policy:
  env:
    set: {{}}
    passthrough: []
  fs:
    allow_read_all: false
    allow_write_all: false
    read_paths: []
    write_paths: []
  net:
    mode: loopback
  platform:
    seatbelt:
      trace: false
""".strip() + "\n"

    # Run composer via stdin
    subprocess.run(
        [sys.executable, "-m", "jupyter_mcp_stdio_guard.jupyter_sandbox_compose", "--config", "-"],
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
        "jupyter_mcp_stdio_guard.jupyter_mcp_launch",
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

    p = subprocess.Popen(launch_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    # MCP stdio protocol: initialize, then execute a code cell
    try:
        _send_line_json(p.stdin, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "clientInfo": {"name": "pytest", "version": "0.0.1"}}
        })
        init_resp = None
        deadline = time.time() + 25.0
        while time.time() < deadline and not init_resp:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == 1 and ("result" in m or "error" in m):
                init_resp = m
        assert init_resp and "result" in init_resp, f"initialize failed: {init_resp}"
        _send_line_json(p.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)

        # Happy-path execution
        code_ok = "print('OK:', 2+2)"
        _send_line_json(p.stdin, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "append_execute_code_cell", "arguments": {"cell_source": code_ok}}
        })
        exec_ok = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not exec_ok:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == 2 and ("result" in m or "error" in m):
                exec_ok = m
        assert exec_ok and "result" in exec_ok, f"code exec failed: {exec_ok}"

        # Sandbox boundary: attempt to write outside runtime_dir should fail
        outside_file = (tmp_path.parent / (tmp_path.name + "_outside") / "denied.txt").as_posix()
        code_denied = f"import pathlib\npathlib.Path('{outside_file}').write_text('x')"
        _send_line_json(p.stdin, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "append_execute_code_cell", "arguments": {"cell_source": code_denied}}
        })
        exec_bad = None
        deadline = time.time() + 45.0
        while time.time() < deadline and not exec_bad:
            m = _read_line_json(p.stdout, 1.0)
            if m and m.get("id") == 3 and ("result" in m or "error" in m):
                exec_bad = m
        # Expect denial reflected as an error or failure text in results
        assert exec_bad and ("error" in exec_bad or "result" in exec_bad), f"no response for denied write: {exec_bad}"
        blob = json.dumps(exec_bad)
        assert ("Permission" in blob) or ("Operation not permitted" in blob) or ("Errno" in blob), blob
    finally:
        try:
            p.terminate()
        except Exception:
            pass
