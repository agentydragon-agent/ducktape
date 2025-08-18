import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _send_line(w, obj: dict) -> None:
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def _read_line(r, timeout: float) -> dict | None:
    import select
    fd = r.fileno()
    os.set_blocking(fd, False)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            b = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not b:
            time.sleep(0.01)
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


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="requires sandbox-exec present even though disabled")
@pytest.mark.skipif(shutil.which("jupyter") is None or shutil.which("jupyter-mcp-server") is None, reason="requires jupyter and jupyter-mcp-server on PATH")
def test_wrapper_unsandbox_initialize_and_hello(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    port = _pick_free_port()

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

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
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
        _send_line(proc.stdin, init)
        resp = _read_line(proc.stdout, 15.0)
        assert resp and resp.get("id") == 1 and "result" in resp, f"initialize failed: {resp}\nstderr:\n{(proc.stderr.read() or b'').decode('utf-8','ignore')[-2000:]}"

        _send_line(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
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
        _send_line(proc.stdin, call)
        resp2 = _read_line(proc.stdout, 20.0)
        assert resp2 and resp2.get("id") == 2 and "result" in resp2, f"tool call failed: {resp2}\nstderr:\n{(proc.stderr.read() or b'').decode('utf-8','ignore')[-2000:]}"

        result = resp2["result"]
        text = json.dumps(result)
        assert "hello world" in text
    finally:
        try:
            proc.terminate(); proc.kill(); proc.wait(timeout=5)
        except Exception:
            pass
