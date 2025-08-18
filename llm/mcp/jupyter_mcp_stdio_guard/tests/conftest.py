import json
import os
import select
import socket
import time
import subprocess
import sys
import shutil
import secrets
from pathlib import Path
from contextlib import contextmanager
import pytest

# Session-wide required binaries/tools; fail-fast once
@pytest.fixture(scope="session", autouse=True)
def _require_env_binaries_and_tools():
    missing = []
    if shutil.which("jupyter") is None:
        missing.append("jupyter")
    if shutil.which("jupyter-mcp-server") is None:
        missing.append("jupyter-mcp-server")
    if sys.platform == "darwin" and shutil.which("sandbox-exec") is None:
        missing.append("sandbox-exec (darwin)")
    if missing:
        pytest.exit(f"Missing required binaries or tools: {', '.join(missing)}", 1)

# Platform-specific optional deps for macOS RTC tests
@pytest.fixture
def require_macos_rtc():
    if sys.platform != "darwin":
        return
    try:
        import jupyter_collaboration  # noqa: F401
        import pycrdt  # noqa: F401
    except Exception as e:
        raise RuntimeError(
            "macOS RTC extensions required (jupyter-collaboration, pycrdt)"
        ) from e

@pytest.fixture
def gen_token() -> str:
    return secrets.token_urlsafe(16)


@pytest.fixture
def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def send_line_json_fn():
    def _send_line_json(w, obj: dict) -> None:
        w.write((json.dumps(obj) + "\n").encode("utf-8"))
        w.flush()
    return _send_line_json


@pytest.fixture
def read_line_json_fn():
    def _read_line_json(r, timeout: float) -> dict | None:
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
    return _read_line_json


@pytest.fixture
def collect_mcp_logs_fn():
    def _collect() -> tuple[str, str]:
        import glob
        out = err = ""
        try:
            for path in sorted(glob.glob("/tmp/sjmcp-*/mcp_stdout.log"))[-3:]:
                try:
                    with open(path, "rb") as fh:
                        out += (
                            f"\n== {path} ==\n" + fh.read().decode("utf-8", "ignore")[-4000:]
                        )
                except OSError:
                    pass
            for path in sorted(glob.glob("/tmp/sjmcp-*/mcp_stderr.log"))[-3:]:
                try:
                    with open(path, "rb") as fh:
                        err += (
                            f"\n== {path} ==\n" + fh.read().decode("utf-8", "ignore")[-4000:]
                        )
                except OSError:
                    pass
        except OSError:
            pass
        return out, err
    return _collect


@pytest.fixture
def mcp_stdio_protocol(send_line_json_fn, read_line_json_fn):
    def _read_until(stdout, match_id: int, total_timeout: float) -> dict | None:
        deadline = time.time() + total_timeout
        while time.time() < deadline:
            m = read_line_json_fn(stdout, 2.0)
            if not m:
                continue
            if m.get("id") == match_id and ("result" in m or "error" in m):
                return m
        return None
    def _protocol(
        stdin,
        stdout,
        tool_name,
        tool_args,
        protocol_version: str = "2025-06-18",
        timeout: float = 30.0,
    ):
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "pytest", "version": "0.0.1"},
            },
        }
        send_line_json_fn(stdin, init)
        resp = _read_until(stdout, 1, 20.0)
        assert resp and resp.get("id") == 1 and "result" in resp, f"initialize failed: {resp}"
        send_line_json_fn(stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)
        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": tool_args},
        }
        send_line_json_fn(stdin, call)
        resp2 = _read_until(stdout, 2, timeout)
        assert resp2 and resp2.get("id") == 2 and "result" in resp2, f"tool call failed: {resp2}"
        return resp2["result"]

    return _protocol

@pytest.fixture
def mcp_call_tool(send_line_json_fn, read_line_json_fn, collect_mcp_logs_fn):
    def _read_until(stdout, match_id: int, total_timeout: float) -> dict | None:
        deadline = time.time() + total_timeout
        while time.time() < deadline:
            m = read_line_json_fn(stdout, 2.0)
            if not m:
                continue
            if m.get("id") == match_id and ("result" in m or "error" in m):
                return m
        return None
    def _call(proc, tool_name: str, tool_args: dict, protocol_version: str = "2025-06-18", init_timeout: float = 25.0, call_timeout: float = 60.0):
        send_line_json_fn(proc.stdin, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": protocol_version, "capabilities": {"tools": {}}, "clientInfo": {"name": "pytest", "version": "0.0.1"}}
        })
        resp = _read_until(proc.stdout, 1, init_timeout)
        if not (resp and resp.get("id") == 1 and "result" in resp):
            out, err = collect_mcp_logs_fn()
            stderr_tail = b""
            stdout_tail = b""
            try:
                if proc.stderr: stderr_tail = proc.stderr.read(20000)
                if proc.stdout: stdout_tail = proc.stdout.read(20000)
            except Exception:
                pass
            pytest.fail(f"initialize failed: {resp}\nstdout tail:\n{stdout_tail[-2000:]}\nstderr tail:\n{stderr_tail[-2000:]}\ntee stdout:\n{out}\ntee stderr:\n{err}")
        send_line_json_fn(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)
        send_line_json_fn(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": tool_args}})
        resp2 = _read_until(proc.stdout, 2, call_timeout)
        if not (resp2 and resp2.get("id") == 2 and "result" in resp2):
            out, err = collect_mcp_logs_fn()
            stderr_tail = b""; stdout_tail = b""
            try:
                if proc.stderr: stderr_tail = proc.stderr.read(20000)
                if proc.stdout: stdout_tail = proc.stdout.read(20000)
            except Exception:
                pass
            pytest.fail(f"tool call failed: {resp2}\nstdout tail:\n{stdout_tail[-2000:]}\nstderr tail:\n{stderr_tail[-2000:]}\ntee stdout:\n{out}\ntee stderr:\n{err}")
        return resp2["result"]
    return _call


@pytest.fixture
def wait_port():
    def _wait(port: int, timeout: float = 15.0) -> bool:
        import socket as _socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with _socket.create_connection(("127.0.0.1", port), 0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    return _wait


@pytest.fixture
def pkg_src_env_update() -> dict:
    pkg_src = Path(__file__).resolve().parents[1] / "src"
    prev = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{pkg_src}:{prev}" if prev else str(pkg_src)}


@pytest.fixture
def launch_proc():
    @contextmanager
    def _run(
        cmd: list[str],
        env_update: dict | None = None,
        cwd: str | os.PathLike | None = None,
    ):
        env = os.environ.copy()
        if env_update:
            env.update(env_update)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        try:
            yield proc
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    return _run


@pytest.fixture
def launch_jupyter_server(tmp_path: Path):
    @contextmanager
    def _start(port: int, token: str):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        nb_rel = Path(".mcp/test.ipynb")
        (ws / nb_rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / nb_rel).write_text(
            json.dumps(
                {
                    "cells": [],
                    "metadata": {
                        "kernelspec": {
                            "name": "python3",
                            "display_name": "Python 3",
                            "language": "python",
                        }
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            )
        )
        js_cmd = [
            "jupyter",
            "server",
            "--port",
            str(port),
            "--ip",
            "127.0.0.1",
            "--ServerApp.root_dir",
            str(ws),
            "--ServerApp.open_browser",
            "False",
            "--ServerApp.token",
            token,
            "--ServerApp.password",
            "",
            "--ServerApp.disable_check_xsrf",
            "True",
        ]
        js_out_path = ws / "jupyter_server.out"
        js_err_path = ws / "jupyter_server.err"
        with js_out_path.open("wb") as js_out, js_err_path.open("wb") as js_err:
            proc = subprocess.Popen(js_cmd, stdout=js_out, stderr=js_err)
            # Wait up to 20s for the port to open before yielding
            deadline = time.time() + 20.0
            ready = False
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.3):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.1)
            try:
                if not ready:
                    raise RuntimeError("Jupyter server did not start listening in time")
                yield ws, nb_rel
            finally:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass

    return _start
