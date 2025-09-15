import json
import os
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from policy_fixture import write_policy as _write_policy


# Session-scoped temp base for tests (pytest-managed)
@pytest.fixture(scope="session")
def test_base(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("mcp_tests")


@pytest.fixture
def artifacts_base(tmp_path: Path) -> Path:
    # Per-test base directory managed by pytest
    return tmp_path


# Bootstrap a dedicated control venv for Jupyter server + MCP bridge, then require tools
@pytest.fixture(scope="session", autouse=True)
def _bootstrap_control_venv_and_require_tools(test_base, request):
    # Skip heavy bootstrap unless explicitly enabled via --run-sandboxer
    if not getattr(request.config.option, "run_sandboxer", False):
        return
    # Always prefer our dedicated control venv; create it if missing, else just prefix PATH
    base = test_base
    control = base / "control_venv"
    py = shutil.which("python3") or sys.executable
    if not (control / "bin" / "python").exists():
        subprocess.run([py, "-m", "venv", str(control)], check=True)
        subprocess.run(
            [
                str(control / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "-U",
                "pip",
                "wheel",
            ],
            check=True,
        )
        subprocess.run(
            [
                str(control / "bin" / "pip"),
                "install",
                "jupyter-server",
                "jupyter-core",
                "jupyter-mcp-server",
                "jupyter-server-ydoc",
                "jupyter-collaboration",
                "pycrdt-websocket",
            ],
            check=True,
        )
    control_bin = str(control / "bin")
    os.environ["SJ_TEST_CONTROL_BIN"] = control_bin
    os.environ["PATH"] = f"{control_bin}:{os.environ.get('PATH', '')}"
    # Ensure package src is importable for subprocesses invoking -m jupyter_mcp_stdio_guard.*
    pkg_src = str(Path(__file__).resolve().parents[1] / "src")
    prev_pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"{pkg_src}:{prev_pp}" if prev_pp else pkg_src
    # Turn on diagnostics and policy echo for tests by default
    os.environ.setdefault("SJ_DEBUG_DIAG", "1")
    # Tighter venv alignment: ensure kernel and wrapper use same interpreter by default
    os.environ.setdefault("SJ_KERNEL_PYTHON", sys.executable)
    # Policy echo will be pointed at per-test run_root/tmp inside provision_ws
    # Now enforce required tools
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
        pytest.skip("macOS-only: RTC extensions")
    try:
        import jupyter_collaboration  # noqa: F401
        import pycrdt  # noqa: F401
    except Exception:
        pytest.skip(
            "macOS RTC extensions not available (jupyter-collaboration, pycrdt)",
        )


# Suite-level opt-in to run slow sandboxer tests


def _is_sandboxer_item(item) -> bool:
    try:
        base_dir = Path(__file__).parent
        p = getattr(item, "path", None)
        if p is None:
            # Fallback for older pytest
            p = Path(str(getattr(item, "fspath", "")))
        return p and Path(p).is_relative_to(base_dir)
    except Exception:
        return False


def pytest_addoption(parser):
    parser.addoption(
        "--run-sandboxer",
        action="store_true",
        help="Run slow sandboxed_jupyter_mcp tests (otherwise each test is SKIPPED loudly)",
    )


# Auto-skip whole suite unless --run-sandboxer; also skip @pytest.mark.macos on non-darwin


def pytest_collection_modifyitems(config, items):
    # Opt-in gate for slow suite (safe when option absent)
    run_flag = getattr(config.option, "run_sandboxer", False)
    if not run_flag:
        skip_all = pytest.mark.skip(
            reason="SLOW suite disabled — pass --run-sandboxer to run",
        )
        for item in items:
            if _is_sandboxer_item(item):
                item.add_marker(skip_all)
        # Do not return; allow other suites to proceed and other hooks to run
        # (we only marked sandboxer tests)

    # Platform-specific skip for macOS-only tests
    if sys.platform != "darwin":
        skip_macos = pytest.mark.skip(reason="macOS-only")
        for item in items:
            if _is_sandboxer_item(item) and "macos" in item.keywords:
                item.add_marker(skip_macos)


# Postmortem artifact collection on failures
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call" or rep.passed:
        return
    # Create artifacts dir under the test's per-test base (fixture)
    base = item.funcargs.get("artifacts_base")
    if base is None:
        # If the test didn't request artifacts_base, fall back to tmp_path if available
        base = item.funcargs.get("tmp_path", Path.cwd())
    dest = Path(base)
    dest.mkdir(parents=True, exist_ok=True)
    # 1) Copy recent /tmp sjmcp logs
    try:
        import glob

        for path in sorted(glob.glob("/tmp/sjmcp-*/mcp_*.log"))[-6:]:
            p = Path(path)
            try:
                (dest / p.name).write_bytes(Path(path).read_bytes())
            except OSError:
                pass
    except Exception:
        pass
    # 2) Copy wrapper run_root logs if available
    rr = os.environ.get("SJ_TEST_RUN_ROOT")
    if rr:
        for rel in [
            "runtime/jupyter_server.out",
            "runtime/jupyter_server.err",
            "runtime/kernel_stderr.log",
            "mcp_stdout.log",
            "mcp_stderr.log",
            "policy.sb",
            "config/jupyter_server_config.py",
            "data/kernels/python3/kernel.json",
            "tmp/seatbelt.trace.log",
        ]:
            p = Path(rr) / rel
            if p.exists():
                try:
                    (dest / p.name).write_bytes(p.read_bytes())
                except OSError:
                    pass
        # Also print tails of key logs to pytest output for convenience
        try:
            for rel in [
                "runtime/jupyter_server.err",
                "runtime/jupyter_server.out",
                "tmp/seatbelt.trace.log",
            ]:
                p = Path(rr) / rel
                if p.exists():
                    tail = p.read_text(errors="ignore").splitlines()[-120:]
                    print(f"\n=== {rel} (tail) ===\n" + "\n".join(tail))
        except Exception:
            pass
    # 3) Copy unsandbox jupyter logs if available
    ws = os.environ.get("SJ_TEST_WS")
    if ws:
        for rel in [
            "jupyter_server.out",
            "jupyter_server.err",
            "logs/jupyter.out",
            "logs/jupyter.err",
        ]:
            p = Path(ws) / rel
            if p.exists():
                try:
                    (dest / p.name).write_bytes(p.read_bytes())
                except OSError:
                    pass
        # Print tails to stdout as well
        try:
            for rel in ["jupyter_server.err", "jupyter_server.out"]:
                p = Path(ws) / rel
                if p.exists():
                    tail = p.read_text(errors="ignore").splitlines()[-120:]
                    print(f"\n=== ws/{rel} (tail) ===\n" + "\n".join(tail))
        except Exception:
            pass
    # 4) On macOS, collect unified log sandbox denies automatically (last 7 minutes)
    if sys.platform == "darwin":
        try:
            last = "7m"
            cmd = [
                "/usr/bin/log",
                "show",
                "--style",
                "syslog",
                "--last",
                last,
                "--predicate",
                '(subsystem == "com.apple.sandbox") && (eventMessage CONTAINS[c] "deny")',
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            (dest / "unified_sandbox_deny.log").write_text(res.stdout)
            # Print a small tail to test output for immediate visibility
            lines = res.stdout.strip().splitlines()
            if lines:
                print(
                    "\n=== unified sandbox denies (tail, last 7m) ===\n" + "\n".join(lines[-200:]),
                )
        except Exception:
            pass


# Policy writer fixture that delegates to the shared policy factory module


@pytest.fixture
def policy_factory():
    return _write_policy


def provision_ws(request, artifacts_base: Path):
    base = artifacts_base
    ws = base / "ws"
    run_root = base / "run_root"
    ws.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    # Expose for postmortem collector
    os.environ["SJ_TEST_RUN_ROOT"] = str(run_root)
    os.environ["SJ_TEST_WS"] = str(ws)
    os.environ["SJ_ARTIFACTS_DIR"] = str(base)
    # Point policy echo at this test's run_root/tmp
    (run_root / "tmp").mkdir(parents=True, exist_ok=True)
    os.environ["SJ_POLICY_ECHO_DIR"] = str(run_root / "tmp")
    return ws, run_root


@pytest.fixture
def provision_ws_with_policy(request, artifacts_base: Path):
    ws, run_root = provision_ws(request, artifacts_base)
    # Prefer param over marker to allow indirect parametrize
    if hasattr(request, "param"):
        kwargs = request.param or {}
    else:
        marker = request.node.get_closest_marker("policy_args")
        kwargs = marker.kwargs if marker else {}
    _write_policy(ws, run_root, **kwargs)
    return ws, run_root


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
                        out += f"\n== {path} ==\n" + fh.read().decode("utf-8", "ignore")[-4000:]
                except OSError:
                    pass
            for path in sorted(glob.glob("/tmp/sjmcp-*/mcp_stderr.log"))[-3:]:
                try:
                    with open(path, "rb") as fh:
                        err += f"\n== {path} ==\n" + fh.read().decode("utf-8", "ignore")[-4000:]
                except OSError:
                    pass
        except OSError:
            pass
        return out, err

    return _collect


@pytest.fixture
def mcp_stdio_protocol(send_line_json_fn, read_line_json_fn):
    def _read_until(
        stdout,
        match_id: int,
        total_timeout: float,
        log_in=None,
    ) -> dict | None:
        deadline = time.time() + total_timeout
        while time.time() < deadline:
            m = read_line_json_fn(stdout, 2.0)
            if not m:
                continue
            if log_in is not None:
                try:
                    log_in.write((json.dumps(m) + "\n").encode("utf-8"))
                    log_in.flush()
                except Exception:
                    pass
            if m.get("id") == match_id and ("result" in m or "error" in m):
                return m
        return None

    def _protocol(
        stdin,
        stdout,
        tool_name,
        tool_args,
        protocol_version: str = "2024-11-05",
        timeout: float = 30.0,
    ):
        artifacts = os.environ.get("SJ_ARTIFACTS_DIR")
        log_out = open(Path(artifacts) / "mcp_protocol_out.log", "ab") if artifacts else None
        log_in = open(Path(artifacts) / "mcp_protocol_in.log", "ab") if artifacts else None
        try:
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
            if log_out is not None:
                log_out.write((json.dumps(init) + "\n").encode("utf-8"))
                log_out.flush()
            send_line_json_fn(stdin, init)
            resp = _read_until(stdout, 1, 20.0, log_in=log_in)
            assert resp and resp.get("id") == 1 and "result" in resp, f"initialize failed: {resp}"
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            if log_out is not None:
                log_out.write((json.dumps(notif) + "\n").encode("utf-8"))
                log_out.flush()
            send_line_json_fn(stdin, notif)
            time.sleep(0.3)
            call = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": tool_args},
            }
            if log_out is not None:
                log_out.write((json.dumps(call) + "\n").encode("utf-8"))
                log_out.flush()
            send_line_json_fn(stdin, call)
            resp2 = _read_until(stdout, 2, timeout, log_in=log_in)
            assert resp2 and resp2.get("id") == 2 and "result" in resp2, f"tool call failed: {resp2}"
            return resp2["result"]
        finally:
            try:
                (log_out and log_out.close())
            except Exception:
                pass
            try:
                (log_in and log_in.close())
            except Exception:
                pass

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

    def _call(
        proc,
        tool_name: str,
        tool_args: dict,
        protocol_version: str = "2024-11-05",
        init_timeout: float = 25.0,
        call_timeout: float = 60.0,
    ):
        send_line_json_fn(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "pytest", "version": "0.0.1"},
                },
            },
        )
        resp = _read_until(proc.stdout, 1, init_timeout)
        if not (resp and resp.get("id") == 1 and "result" in resp):
            out, err = collect_mcp_logs_fn()
            stderr_tail = b""
            stdout_tail = b""
            try:
                if proc.stderr:
                    stderr_tail = proc.stderr.read(20000)
                if proc.stdout:
                    stdout_tail = proc.stdout.read(20000)
            except Exception:
                pass
            pytest.fail(
                f"initialize failed: {resp}\nstdout tail:\n{stdout_tail[-2000:]}\nstderr tail:\n{stderr_tail[-2000:]}\ntee stdout:\n{out}\ntee stderr:\n{err}",
            )
        send_line_json_fn(
            proc.stdin,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        time.sleep(0.3)
        send_line_json_fn(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": tool_args},
            },
        )
        resp2 = _read_until(proc.stdout, 2, call_timeout)
        if not (resp2 and resp2.get("id") == 2 and "result" in resp2):
            out, err = collect_mcp_logs_fn()
            stderr_tail = b""
            stdout_tail = b""
            try:
                if proc.stderr:
                    stderr_tail = proc.stderr.read(20000)
                if proc.stdout:
                    stdout_tail = proc.stdout.read(20000)
            except Exception:
                pass
            pytest.fail(
                f"tool call failed: {resp2}\nstdout tail:\n{stdout_tail[-2000:]}\nstderr tail:\n{stderr_tail[-2000:]}\ntee stdout:\n{out}\ntee stderr:\n{err}",
            )
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
        # If artifacts dir set, tee child stderr to file automatically
        artifacts = os.environ.get("SJ_ARTIFACTS_DIR")
        t = None
        if artifacts:
            dest = Path(artifacts) / "child_stderr.log"

            def _drain_err():
                try:
                    with dest.open("ab", buffering=0) as f:
                        while True:
                            chunk = proc.stderr.readline()
                            if not chunk:
                                break
                            f.write(chunk)
                except Exception:
                    pass

            t = threading.Thread(target=_drain_err, daemon=True)
            t.start()
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
def launch_jupyter_server(request, artifacts_base: Path):
    @contextmanager
    def _start(port: int, token: str):
        base = artifacts_base
        ws = base / "ws"
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
                        },
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                },
            ),
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
            # Wait up to 30s for the port to open before yielding (Jupyter can be slow to start)
            deadline = time.time() + 30.0
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
                    # Read last lines of Jupyter logs for diagnostics
                    try:
                        j_out = (ws / "jupyter_server.out").read_text(errors="ignore").splitlines()[-80:]
                    except Exception:
                        j_out = []
                    try:
                        j_err = (ws / "jupyter_server.err").read_text(errors="ignore").splitlines()[-80:]
                    except Exception:
                        j_err = []
                    raise RuntimeError(
                        "Jupyter server did not start listening in time\n"
                        + "=== jupyter_server.out (tail) ===\n"
                        + "\n".join(j_out)
                        + "\n=== jupyter_server.err (tail) ===\n"
                        + "\n".join(j_err),
                    )
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
