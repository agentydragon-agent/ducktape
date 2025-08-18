#!/usr/bin/env python3
import argparse
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime
import socket
from pathlib import Path

SANDBOX_POLICY_BASE = """
(version 1)
(deny default)

(allow process*)
(allow signal (target self))

(allow file-read*)
(allow file* (literal "/dev/null"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file* (subpath "/dev/tty"))

(allow ipc-posix-shm)
(allow ipc-posix-sem)
(allow ipc-sysv-shm)
(allow mach-lookup)
(allow system-socket)
(allow sysctl-read)

(allow network-outbound)
(allow network-inbound (local ip))
"""


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _ensure_document_id(
    workspace: Path, document_id: str | None, sandboxed_kernel: bool
) -> str:
    if document_id:
        p = workspace / document_id
    else:
        rel = (
            Path(".mcp")
            / "scratch"
            / (
                datetime.utcnow().strftime("%Y%m%dT%H%M%S")
                + "-"
                + secrets.token_hex(4)
                + ".ipynb"
            )
        )
        p = workspace / rel
        document_id = str(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f"Notebook already exists: {p}")
    kernelspec = (
        {
            "name": "python3-sandboxed",
            "display_name": "Python (Sandboxed)",
            "language": "python",
        }
        if sandboxed_kernel
        else {"name": "python3", "display_name": "Python 3", "language": "python"}
    )
    p.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "kernelspec": kernelspec,
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            },
        ),
    )
    return document_id


def _build_bash_script(
    workspace: Path,
    document_id: str,
    token: str,
    start_new_runtime: bool,
) -> str:
    wq = shlex.quote(str(workspace))
    dq = shlex.quote(document_id)
    tq = shlex.quote(token)
    return f"""
set -euo pipefail
trap 'kill "$JPID" 2>/dev/null || true' EXIT
# Launch Jupyter Server in background with logs redirected to runtime dir
jupyter server \
  --port "$JP_PORT" \
  --ip 127.0.0.1 \
  --ServerApp.root_dir {wq} \
  --ServerApp.open_browser=False \
  --ServerApp.token {tq} \
  --ServerApp.password '' \
  --ServerApp.disable_check_xsrf True \
  1>"$JUPYTER_RUNTIME_DIR/jupyter_server.out" 2>"$JUPYTER_RUNTIME_DIR/jupyter_server.err" &
JPID=$!
# Wait for port to become ready (up to ~10s)
python3 - "$JP_PORT" <<'PY'
import socket, sys, time
port=int(sys.argv[1])
for _ in range(20):
    try:
        with socket.create_connection(("127.0.0.1", port), 0.5):
            sys.exit(0)
    except OSError:
        time.sleep(0.5)
sys.exit(1)
PY
# Now exec the stdio MCP server in foreground (inherits stdio)
exec jupyter-mcp-server start \
  --transport stdio \
  --provider jupyter \
  --document-url http://127.0.0.1:$JP_PORT \
  --document-id {dq} \
  --document-token {tq} \
  --runtime-url http://127.0.0.1:$JP_PORT \
  --runtime-token {tq} \
  --start-new-runtime {("true" if start_new_runtime else "false")}
""".strip()


def _docker(
    workspace: Path,
    document_id: str,
    docker_image: str,
    start_new_runtime: bool,
    jupyter_port: int,
) -> int:
    token = secrets.token_urlsafe(24)
    bash_script = _build_bash_script(
        Path("/workspace"),
        document_id,
        token,
        start_new_runtime,
    )
    run_root = f"/tmp/sjmcp-{secrets.token_hex(6)}"
    env_flags = [
        "-e",
        f"JP_PORT={jupyter_port}",
        "-e",
        f"JUPYTER_RUNTIME_DIR={run_root}/runtime",
        "-e",
        f"JUPYTER_DATA_DIR={run_root}/data",
        "-e",
        f"JUPYTER_CONFIG_DIR={run_root}/config",
        "-e",
        f"MPLCONFIGDIR={run_root}/mpl",
    ]
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        *env_flags,
        "-v",
        f"{workspace}:/workspace",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        docker_image,
        "bash",
        "-lc",
        bash_script,
    ]
    return subprocess.Popen(cmd).wait()


def _write_sandboxed_kernelspec(
    run_root: Path,
    workspace: Path,
    policy_path: Path,
) -> None:
    ks_dir = run_root / "data" / "kernels" / "python3-sandboxed"
    ks_dir.mkdir(parents=True, exist_ok=True)
    kernel_json = {
        "argv": [
            "sandbox-exec",
            "-f",
            str(policy_path),
            "-D",
            f"WORKSPACE={workspace}",
            "-D",
            f"RUN_ROOT={run_root}",
            sys.executable,
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "display_name": "Python (Sandboxed)",
        "language": "python",
        "env": {},
    }
    (ks_dir / "kernel.json").write_text(json.dumps(kernel_json))


def _start_jupyter_server(
    workspace: Path,
    token: str,
    jupyter_port: int,
    run_root: Path,
    env: dict[str, str],
) -> subprocess.Popen:
    out_path = run_root / "runtime" / "jupyter_server.out"
    err_path = run_root / "runtime" / "jupyter_server.err"
    out_f = out_path.open("a", buffering=1)
    err_f = err_path.open("a", buffering=1)
    cmd = [
        "jupyter",
        "server",
        "--port",
        str(jupyter_port),
        "--ip",
        "127.0.0.1",
        "--ServerApp.root_dir",
        str(workspace),
        "--ServerApp.open_browser",
        "False",
        "--ServerApp.token",
        token,
        "--ServerApp.password",
        "",
        "--ServerApp.disable_check_xsrf",
        "True",
    ]
    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=env)

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", jupyter_port), 0.5):
                break
        except OSError:
            time.sleep(0.25)
    return proc


def _seatbelt(
    workspace: Path,
    document_id: str,
    start_new_runtime: bool,
    jupyter_port: int,
    trace: bool = True,
    kernel_sandbox: bool = True,
) -> int:
    token = secrets.token_urlsafe(24)
    run_root = Path(tempfile.mkdtemp(prefix="sjmcp-", dir="/tmp"))
    for sub in ("runtime", "data", "config", "mpl"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    policy_path = run_root / "policy.sb"
    # Compose final policy with dynamic write roots and optional tracing
    dyn_lines = [
        '(allow file* (subpath (param "WORKSPACE")))',
        '(allow file* (subpath (param "RUN_ROOT")))',
        '(allow file* (subpath "/tmp"))',
        '(allow file* (subpath "/private/tmp"))',
    ]
    if trace:
        dyn_lines.insert(0, f'(trace "{run_root / "profile.sb"!s}")')
    policy_text = SANDBOX_POLICY_BASE + "\n" + "\n".join(dyn_lines) + "\n"
    policy_path.write_text(policy_text)
    if kernel_sandbox:
        _write_sandboxed_kernelspec(run_root, workspace, policy_path)
    print(
        f"[wrapper] run_root={run_root} workspace={workspace}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[wrapper] jupyter: http://127.0.0.1:{jupyter_port} token=REDACTED",
        file=sys.stderr,
        flush=True,
    )
    if trace:
        print(
            f"[seatbelt] Sandbox trace enabled. policy={policy_path} trace={run_root / 'profile.sb'}",
            file=sys.stderr,
            flush=True,
        )
    child_env = os.environ.copy()
    child_env.update(
        {
            "JP_PORT": str(jupyter_port),
            "JUPYTER_RUNTIME_DIR": str(run_root / "runtime"),
            "JUPYTER_DATA_DIR": str(run_root / "data"),
            "JUPYTER_CONFIG_DIR": str(run_root / "config"),
            "MPLCONFIGDIR": str(run_root / "mpl"),
            "JUPYTER_TOKEN": token,
            "PYTHONUNBUFFERED": "1",
        },
    )
    # Start Jupyter Server unsandboxed (kernel is sandboxed via kernelspec)
    jl = _start_jupyter_server(workspace, token, jupyter_port, run_root, child_env)
    # Start MCP server (stdio: newline-delimited JSON); tee child stdout/stderr to files and parent stdio
    mcp_cmd = [
        "jupyter-mcp-server",
        "start",
        "--transport",
        "stdio",
        "--provider",
        "jupyter",
        "--document-url",
        f"http://127.0.0.1:{jupyter_port}",
        "--document-id",
        document_id,
        "--document-token",
        token,
        "--runtime-url",
        f"http://127.0.0.1:{jupyter_port}",
        "--runtime-token",
        token,
        "--start-new-runtime",
        "true" if start_new_runtime else "false",
    ]
    mcp_stdout_path = run_root / "mcp_stdout.log"
    mcp_stderr_path = run_root / "mcp_stderr.log"
    print(f"[wrapper] mcp_cmd={' '.join(mcp_cmd)}", file=sys.stderr, flush=True)
    mcp = subprocess.Popen(
        mcp_cmd, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(
        f"[wrapper] mcp_stdout={mcp_stdout_path} mcp_stderr={mcp_stderr_path}",
        file=sys.stderr,
        flush=True,
    )

    def _tee_stream(src, dest_file_path: Path, dest_buffer):
        with dest_file_path.open("ab", buffering=0) as f:
            while True:
                chunk = src.readline()
                if not chunk:
                    break
                try:
                    dest_buffer.write(chunk)
                    dest_buffer.flush()
                except (BrokenPipeError, ValueError) as e:
                    print(f"[wrapper] tee write to parent failed: {e}", file=sys.stderr)
                try:
                    f.write(chunk)
                except OSError as e:
                    print(f"[wrapper] tee write to log failed: {e}", file=sys.stderr)

    t_out = threading.Thread(
        target=_tee_stream,
        args=(mcp.stdout, mcp_stdout_path, sys.stdout.buffer),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_tee_stream,
        args=(mcp.stderr, mcp_stderr_path, sys.stderr.buffer),
        daemon=True,
    )
    t_out.start()
    t_err.start()
    try:
        return mcp.wait()
    finally:
        try:
            mcp.terminate()
        except Exception as e:
            print(f"[wrapper] mcp terminate failed: {e}", file=sys.stderr)
        try:
            jl.terminate()
        except Exception as e:
            print(f"[wrapper] jupyter terminate failed: {e}", file=sys.stderr)
        try:
            mcp.wait(timeout=5)
        except Exception as e:
            print(f"[wrapper] mcp wait failed: {e}", file=sys.stderr)
        try:
            jl.wait(timeout=5)
        except Exception as e:
            print(f"[wrapper] jupyter wait failed: {e}", file=sys.stderr)
        if not trace:
            try:
                shutil.rmtree(run_root, ignore_errors=True)
            except Exception as e:
                print(f"[wrapper] cleanup failed: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=str(Path.cwd()))
    ap.add_argument("--document-id", default=None)
    ap.add_argument("--mode", choices=["docker", "seatbelt"], default="seatbelt")
    ap.add_argument("--docker-image", default="python:3.12-slim")
    ap.add_argument("--jupyter-port", type=int, default=0, help="0=auto-pick free port")
    ap.add_argument("--start-new-runtime", action="store_true")
    ap.add_argument("--trace-sandbox", action="store_true")
    ap.add_argument("--no-kernel-sandbox", action="store_true")
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    _ensure_dir(workspace)
    doc_id = _ensure_document_id(
        workspace, args.document_id, sandboxed_kernel=not args.no_kernel_sandbox
    )
    port = args.jupyter_port or 0
    if port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    if args.mode == "docker":
        return _docker(
            workspace,
            doc_id,
            args.docker_image,
            args.start_new_runtime,
            port,
        )
    return _seatbelt(
        workspace,
        doc_id,
        args.start_new_runtime,
        port,
        trace=args.trace_sandbox,
        kernel_sandbox=not args.no_kernel_sandbox,
    )
