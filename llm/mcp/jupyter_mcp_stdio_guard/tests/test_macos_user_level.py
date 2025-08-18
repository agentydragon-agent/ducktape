import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import shutil
import pytest


def run_log_show(pred: str, minutes: int = 2) -> str:
    try:
        out = subprocess.check_output(
            [
                "log",
                "show",
                "--style",
                "syslog",
                "--last",
                f"{minutes}m",
                "--predicate",
                pred,
            ],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
        )
        return out
    except Exception as e:
        return f"<log show failed: {e}>"


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def send_line_json(w, obj: dict):
    # MCP stdio uses newline-delimited JSON without headers
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def read_line_json(r, deadline: float) -> dict | None:
    # Read one newline-delimited JSON object safely with non-blocking polling; accept LF or CRLF
    import select, os as _os
    fd = r.fileno()
    buf = bytearray()
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            ch = _os.read(fd, 1)
        except Exception:
            time.sleep(0.01)
            continue
        if not ch:
            time.sleep(0.01)
            continue
        if ch == b"\n":
            break
        buf.extend(ch)
    if not buf:
        return None
    try:
        text = bytes(buf).decode("utf-8", errors="ignore").rstrip("\r")
        return json.loads(text)
    except Exception:
        return None


def test_user_view_end_to_end(tmp_path: Path):
    # Prerequisites: Jupyter RTC extension dependencies required by jupyter-mcp-server
    try:
        import jupyter_collaboration  # noqa: F401
        # datalayer-pycrdt installs importable module name 'pycrdt'
        import pycrdt  # noqa: F401
    except Exception:
        raise AssertionError("Missing required packages: jupyter-collaboration==4.0.2 and datalayer-pycrdt==0.12.17; install per pyproject to run this test.")

    if shutil.which("sandbox-exec") is None:
        pytest.skip("sandbox-exec not found")
    if shutil.which("jupyter") is None or shutil.which("jupyter-mcp-server") is None:
        pytest.skip("jupyter or jupyter-mcp-server not available in PATH")

    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    port = pick_free_port()
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        # Ensure module import path
        pkg_src = Path(__file__).resolve().parents[1] / "src"
        env["PYTHONPATH"] = f"{pkg_src}:{env.get('PYTHONPATH', '')}"
        # Only provide the port; wrapper will allocate per-session dirs
        env["JP_PORT"] = str(port)

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
            "--trace-sandbox",
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # initialize
            init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "user-test", "version": "1.0"},
                },
            }
            send_line_json(proc.stdin, init)
            # Read until we see initialize result or any other message for diagnostics
            deadline = time.time() + 8
            msg = None
            while time.time() < deadline and proc.poll() is None:
                m = read_line_json(proc.stdout, time.time() + 2)
                if m is None:
                    continue
                if m.get("id") == 1 and ("result" in m or "error" in m):
                    msg = m
                    break
            if not (msg and msg.get("id") == 1 and "result" in msg):
                # Kill the proc to avoid blocking and then collect logs
                try:
                    proc.terminate(); proc.kill(); proc.wait(timeout=5)
                except Exception:
                    pass
                stderr_tail = proc.stderr.read(16000) if proc.stderr else b""
                stdout_tail = proc.stdout.read(16000) if proc.stdout else b""
                # Pull tee logs
                mcp_out = mcp_err = ""
                try:
                    import glob
                    for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stdout.log'))[-3:]:
                        try:
                            mcp_out += f"\n== {path} ==\n" + open(path,'rb').read().decode('utf-8','ignore')[-4000:]
                        except Exception:
                            pass
                    for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stderr.log'))[-3:]:
                        try:
                            mcp_err += f"\n== {path} ==\n" + open(path,'rb').read().decode('utf-8','ignore')[-4000:]
                        except Exception:
                            pass
                except Exception:
                    pass
                sb_log = run_log_show('subsystem == "com.apple.sandbox"')
                sbox_log = run_log_show('process == "sandbox-exec"')
                jlab_log = run_log_show('eventMessage CONTAINS "ServerApp"')
                # Pull tee logs
                mcp_out = mcp_err = ""
                try:
                    import glob
                    for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stdout.log'))[-3:]:
                        try:
                            mcp_out += f"\n== {path} ==\n" + open(path,'rb').read().decode('utf-8','ignore')[-4000:]
                        except Exception:
                            pass
                    for path in sorted(glob.glob('/tmp/sjmcp-*/mcp_stderr.log'))[-3:]:
                        try:
                            mcp_err += f"\n== {path} ==\n" + open(path,'rb').read().decode('utf-8','ignore')[-4000:]
                        except Exception:
                            pass
                except Exception:
                    pass
                (tmp_path / "stdout.log").write_text(
                    stdout_tail.decode("utf-8", errors="ignore")
                )
                (tmp_path / "stderr.log").write_text(
                    stderr_tail.decode("utf-8", errors="ignore")
                )
                (tmp_path / "sandbox_subsystem.log").write_text(sb_log)
                (tmp_path / "sandbox_exec.log").write_text(sbox_log)
                (tmp_path / "jupyter_server.log").write_text(jlab_log)
                (tmp_path / "mcp_stdout.log").write_text(mcp_out)
                (tmp_path / "mcp_stderr.log").write_text(mcp_err)
                pytest.fail(
                    "\n".join(
                        [
                            "initialize failed or no response.",
                            f"cmd={' '.join(cmd)}",
                            f"msg={msg}",
                            f"stdout tail:\n{stdout_tail[-2000:]!r}",
                            f"stderr tail:\n{stderr_tail[-2000:]!r}",
                            f"mcp_stdout tails:{mcp_out}",
                            f"mcp_stderr tails:{mcp_err}",
                            f"sandbox_subsystem.log tail:\n{sb_log[-2000:]}",
                            f"sandbox_exec.log tail:\n{sbox_log[-2000:]}",
                            f"jupyter_server.log tail:\n{jlab_log[-2000:]}",
                            f"logs in {tmp_path}",
                        ]
                    )
                )

            # Send MCP 'notifications/initialized' after successful initialize
            send_line_json(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})

            # Send MCP 'notifications/initialized' after successful initialize
            send_line_json(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            time.sleep(0.3)

            # call tool
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
            msg2 = read_line_json(proc.stdout, time.time() + 15)
            if not (msg2 and msg2.get("id") == 2 and "result" in msg2):
                try:
                    proc.terminate(); proc.kill(); proc.wait(timeout=5)
                except Exception:
                    pass
                out_tail = b""; err_tail = b""
                try:
                    import os, select
                    if proc.stdout:
                        fd = proc.stdout.fileno(); os.set_blocking(fd, False)
                        r,_,_ = select.select([fd], [], [], 0.1)
                        if r:
                            out_tail = os.read(fd, 4096)
                    if proc.stderr:
                        fd2 = proc.stderr.fileno(); os.set_blocking(fd2, False)
                        r,_,_ = select.select([fd2], [], [], 0.1)
                        if r:
                            err_tail = os.read(fd2, 4096)
                except Exception:
                    pass
                pytest.fail(
                    f"No tool result. cmd={' '.join(cmd)}\n"
                    f"init={msg}\n"
                    f"resp={msg2}\n"
                    f"stderr tail={err_tail!r}\nstdout tail={out_tail!r}"
                )
            # result may be a list of strings
            res = msg2["result"]
            joined = "\n".join(map(str, res if isinstance(res, list) else [res]))
            assert "hello world" in joined
        finally:
            proc.kill()
            proc.wait(timeout=5)
