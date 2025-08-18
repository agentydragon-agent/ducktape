import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Fixtures are provided by local conftest.py; use by parameter injection


# Hard dependencies: on Darwin, require sandbox-exec; require jupyter and jupyter-mcp-server on PATH
if sys.platform == "darwin" and shutil.which("sandbox-exec") is None:
    raise RuntimeError("sandbox-exec is required on macOS")
if shutil.which("jupyter") is None or shutil.which("jupyter-mcp-server") is None:
    raise RuntimeError("jupyter and jupyter-mcp-server must be on PATH")


def test_wrapper_unsandbox_initialize_and_hello(
    tmp_path: Path, pick_free_port, send_line_json_fn, read_line_json_fn
):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    port = pick_free_port() if callable(pick_free_port) else pick_free_port

    env = os.environ.copy()
    pkg_src = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = f"{pkg_src}:{env.get('PYTHONPATH', '')}"

    cmd = [
        sys.executable,
        "-m",
        "jupyter_mcp_stdio_guard",
        "--workspace",
        str(ws),
        "--mode",
        "seatbelt",
        "--jupyter-port",
        str(port),
        "--no-kernel-sandbox",
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "wrapper-unsandbox-smoke", "version": "0.0.1"},
            },
        }
        send_line_json = send_line_json_fn
        read_line_json = read_line_json_fn
        send_line_json(proc.stdin, init)
        resp = read_line_json(proc.stdout, 15.0)
        assert resp and resp.get("id") == 1 and "result" in resp, (
            f"initialize failed: {resp}\nstderr:\n{(proc.stderr.read() or b'').decode('utf-8', 'ignore')[-2000:]}"
        )

        send_line_json(
            proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        time.sleep(0.3)

        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "append_execute_code_cell",
                "arguments": {"cell_source": "print('hello world')"},
            },
        }
        send_line_json(proc.stdin, call)
        resp2 = read_line_json(proc.stdout, 20.0)
        assert resp2 and resp2.get("id") == 2 and "result" in resp2, (
            f"tool call failed: {resp2}\nstderr:\n{(proc.stderr.read() or b'').decode('utf-8', 'ignore')[-2000:]}"
        )

        result = resp2["result"]
        text = json.dumps(result)
        assert "hello world" in text
    finally:
        try:
            proc.terminate()
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
