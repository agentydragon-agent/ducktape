from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time

import docker
from pydantic import BaseModel
import yaml

from adgn.mcp._shared.constants import SLEEP_FOREVER_CMD
from adgn.llm.sandboxer import Policy


# Legacy wrapper PolicyConfig retained only for import compatibility in older tests; wrapper no longer uses it.
class PolicyConfig(BaseModel):
    class Config:
        extra = "forbid"


# Utilities


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _ensure_document_id(workspace: Path, document_id: str | None) -> str:
    if document_id is not None:
        resolved_id = document_id
        target_path = workspace / document_id
    else:
        rel = (
            Path(".mcp")
            / "scratch"
            / (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
                + "-"
                + secrets.token_hex(4)
                + ".ipynb"
            )
        )
        resolved_id = str(rel)
        target_path = workspace / rel
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(f"Notebook already exists: {target_path}")
    kernelspec = {"name": "python3", "display_name": "Python 3", "language": "python"}
    target_path.write_text(
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
    return resolved_id


# Docker mode helper (unchanged behavior aside from workspace/run_root coming from CLI)


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

    # Prepare environment for the container
    env = {
        "JP_PORT": str(jupyter_port),
        "JUPYTER_RUNTIME_DIR": f"{run_root}/runtime",
        "JUPYTER_DATA_DIR": f"{run_root}/data",
        "JUPYTER_CONFIG_DIR": f"{run_root}/config",
        "MPLCONFIGDIR": f"{run_root}/mpl",
    }

    # Start a background container via Docker SDK; keep it alive and exec the script to preserve stdio semantics
    name = f"sjmcp-{secrets.token_hex(6)}"
    try:
        dclient = docker.from_env()
        dclient.ping()
    except Exception as e:
        print(f"[wrapper] ERROR: Docker daemon not reachable: {e}", file=sys.stderr)
        return 2

    container = None
    try:
        try:
            # Standardize long-lived container command across wrappers

            container = dclient.containers.run(
                image=docker_image,
                command=SLEEP_FOREVER_CMD,
                name=name,
                remove=True,
                detach=True,
                environment=env,
                volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                working_dir="/workspace",
            )
        except Exception as e:
            print(f"[wrapper] ERROR: failed to start container: {e}", file=sys.stderr)
            return 2

        # Run the jupyter+mcp startup script inside the container attached to our stdio
        exec_cmd = [
            "docker",
            "exec",
            "-i",
            name,
            "bash",
            "-lc",
            bash_script,
        ]
        return subprocess.Popen(exec_cmd).wait()
    finally:
        try:
            if container is not None:
                container.stop()
        except Exception:
            pass


# Jupyter helpers


def _kernels_dir(run_root: Path) -> Path:
    return run_root / "data" / "kernels"


def _write_sandboxed_kernelspec(
    run_root: Path,
    workspace: Path,
    policy_yaml: Path,
    kernel_python: str,
    *,
    trace: bool,
) -> None:
    # Override the default 'python3' kernel to ensure the sandbox is used.
    ks_dir = _kernels_dir(run_root) / "python3"
    ks_dir.mkdir(parents=True, exist_ok=True)
    argv: list[str] = [
        sys.executable,
        "-m",
        "adgn.llm.sandboxer",
        "--policy",
        str(policy_yaml),
    ]
    if trace:
        argv.append("--trace")
    # Enable sandboxer debug when SJ_DEBUG_DIAG is set to surface policy path and -D params
    if os.environ.get("SJ_DEBUG_DIAG"):
        argv.append("--debug")
    # Always exec kernel via our tiny exec wrapper to capture stderr reliably;
    # it will choose shim vs ipykernel based on SJ_DEBUG_DIAG
    argv += [
        "--",
        kernel_python,
        "-m",
        "adgn.mcp.sandboxed_jupyter_mcp.kernel_exec",
        "--stderr-log",
        str((run_root / "runtime" / "kernel_stderr.log").as_posix()),
        "--",
        "-f",
        "{connection_file}",
    ]
    kernel_env = {"SJ_KERNEL_SANDBOXED": "1", "SJ_POLICY_PATH": str(policy_yaml)}
    # If diagnostics are enabled, increase kernel-side verbosity to aid debugging
    if os.environ.get("SJ_DEBUG_DIAG"):
        kernel_env.update(
            {
                "PYTHONFAULTHANDLER": "1",
                "PYTHONVERBOSE": "1",
            },
        )
    kernel_json = {
        "argv": argv,
        "display_name": "Python 3",
        "language": "python",
        "env": kernel_env,
    }
    (ks_dir / "kernel.json").write_text(json.dumps(kernel_json))


def _start_jupyter_server(
    workspace: Path,
    token: str,
    jupyter_port: int,
    run_root: Path,
    env: dict[str, str],
    kernel_default_name: str | None = None,
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
        "--ServerApp.log_level",
        "DEBUG",
        "--config",
        str(run_root / "config" / "jupyter_server_config.py"),
    ]
    if kernel_default_name:
        cmd += [
            "--ServerApp.default_kernel_name",
            kernel_default_name,
            "--NotebookApp.default_kernel_name",
            kernel_default_name,
        ]
    # Turn on RTC/ydoc deps visibility and quieter platformdirs warning
    env = dict(env)
    env.setdefault("JUPYTER_PLATFORM_DIRS", "1")
    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=env)

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", jupyter_port), 0.5):
                break
        except OSError:
            time.sleep(0.25)
    return proc


# Seatbelt mode


def _seatbelt(
    *,
    workspace: Path,
    run_root: Path,
    document_id: str,
    start_new_runtime: bool,
    jupyter_port: int,
    env_set: dict[str, str],
    env_passthrough: list[str],
    policy_yaml: Path,
    trace: bool = True,
    kernel_sandbox: bool = True,
    kernel_python: str,
    debug_diag: bool = False,
) -> int:
    token = secrets.token_urlsafe(24)
    for sub in ("runtime", "data", "config", "mpl", "pycache", "cache", "tmp"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    # Delegate sandboxing to sandboxer (called by kernelspec). Wrapper no longer writes seatbelt profiles.

    if kernel_sandbox:
        _write_sandboxed_kernelspec(
            run_root,
            workspace,
            policy_yaml,
            kernel_python=kernel_python,
            trace=trace,
        )
        # Ensure newly created notebooks default to the sandboxed kernel
        (run_root / "runtime" / "kernels.json").write_text(
            json.dumps({"default": "python3"}),
        )

    print(
        f"[wrapper] run_root={run_root!s} workspace={workspace!s}",
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
            f"[seatbelt] Sandbox trace enabled. policy_yaml={policy_yaml!s}",
            file=sys.stderr,
            flush=True,
        )

    # Child environment: explicit env + passthrough
    child_env: dict[str, str] = dict(env_set or {})
    for k in env_passthrough or []:
        if k in os.environ:
            child_env[k] = os.environ[k]

    # Diagnostics: print child toolchain versions and paths (behind flag/env)
    if debug_diag or os.environ.get("SJ_DEBUG_DIAG"):

        def _run_out(args: list[str]) -> str:
            try:
                cp = subprocess.run(
                    args,
                    check=False,
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return cp.stdout.strip()
            except Exception as e:
                return f"<error: {e}>"

        try:
            child_path = child_env.get("PATH", os.environ.get("PATH", ""))
            jup_path = shutil.which("jupyter", path=child_path) or "<not found>"
            jms_path = (
                shutil.which("jupyter-mcp-server", path=child_path) or "<not found>"
            )
            print(f"[diag] child PATH={child_path}", file=sys.stderr)
            print(f"[diag] which jupyter -> {jup_path}", file=sys.stderr)
            print(
                f"[diag] jupyter --version ->\n{_run_out(['jupyter', '--version'])}",
                file=sys.stderr,
            )
            print(
                f"[diag] jupyter server --version ->\n{_run_out(['jupyter', 'server', '--version'])}",
                file=sys.stderr,
            )
            print(f"[diag] which jupyter-mcp-server -> {jms_path}", file=sys.stderr)
            _jms_help = _run_out(["jupyter-mcp-server", "--help"])
            print(
                f"[diag] jupyter-mcp-server --help (head) ->\n{_jms_help.splitlines()[0] if _jms_help else ''}",
                file=sys.stderr,
            )
            print(
                f"[diag] parent python={sys.executable} {sys.version.split()[0]}",
                file=sys.stderr,
            )
            kp_out = _run_out([kernel_python, "--version"])
            print(f"[diag] kernel python={kernel_python} -> {kp_out}", file=sys.stderr)
        except Exception as e:
            print(f"[diag] version diagnostics failed: {e}", file=sys.stderr)

    # Write a server config to prefer our kernels only
    (run_root / "config").mkdir(parents=True, exist_ok=True)
    (run_root / "config" / "jupyter_server_config.py").write_text(
        "\n".join(
            [
                "c = get_config()",
                "# kernel search path set via JUPYTER_PATH; kernel_dirs not supported on this ServerApp",
                "c.KernelSpecManager.ensure_native_kernel = False",
                # Avoid default_kernel_name trait to prevent notebook_shim errors
                "c.ServerApp.open_browser = False",
                "c.ServerApp.ip = '127.0.0.1'",
                "c.ServerApp.disable_check_xsrf = True",
                # Allow serving hidden .mcp/ paths for test notebooks
                "c.ContentsManager.allow_hidden = True",
                # Enable RTC/ydoc so collaboration/session API exists for nbmodel client
                "c.ServerApp.collaborative = True",
                "c.ServerApp.jpserver_extensions = {'jupyter_server_ydoc': True}",
                # Capture kernel stderr to a file for diagnostics
                # (set on base KernelManager so it applies to sub-managers)
                f"c.KernelManager.kernel_log_file = '{(run_root / 'runtime' / 'kernel_stderr.log').as_posix()}'",
            ],
        ),
    )

    # Start Jupyter Server (unsandboxed; kernel is sandboxed)
    jl = _start_jupyter_server(
        workspace,
        token,
        jupyter_port,
        run_root,
        child_env,
        kernel_default_name=None,
    )

    # Start MCP server (stdio)
    # Resolve jupyter-mcp-server using the child environment PATH so policy-provided PATH is honored.
    _which_path = child_env.get("PATH", os.environ.get("PATH", ""))
    if not shutil.which("jupyter-mcp-server", path=_which_path):
        raise FileNotFoundError(
            "jupyter-mcp-server not found on PATH (checked child env)",
        )
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
    _cmd_log = " ".join(mcp_cmd).replace(token, "REDACTED")
    print(f"[wrapper] mcp_cmd={_cmd_log}", file=sys.stderr, flush=True)
    print(
        f"[wrapper] mcp_stdout={mcp_stdout_path} mcp_stderr={mcp_stderr_path}",
        file=sys.stderr,
        flush=True,
    )
    # Ensure sandboxer echoes policy if requested
    # Tests can set SJ_POLICY_ECHO_DIR=run_root/tmp to capture policy.sb and defs

    # Run MCP server with inherited stdio so the parent test process can talk JSON-RPC directly.
    proc = subprocess.Popen(mcp_cmd, env=child_env)
    rc: int | None = None
    try:
        rc = proc.wait()
        print(f"[wrapper] mcp exited rc={rc}", file=sys.stderr, flush=True)
    finally:
        try:
            if proc.returncode is None:
                proc.terminate()
        except Exception:
            pass
        # Always shut down Jupyter server we spawned
        try:
            jl.terminate()
        except Exception as e:
            print(f"[wrapper] jupyter terminate failed: {e}", file=sys.stderr)
        try:
            jl.wait(timeout=5)
        except Exception as e:
            print(f"[wrapper] jupyter wait failed: {e}", file=sys.stderr)
        if not trace:
            try:
                shutil.rmtree(run_root, ignore_errors=True)
            except Exception as e:
                print(f"[wrapper] cleanup failed: {e}", file=sys.stderr)
    return rc if rc is not None else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="sandbox-jupyter-mcp")
    sub = ap.add_subparsers(dest="command", required=True)

    ap_stdio = sub.add_parser(
        "stdio",
        help="Start MCP server over stdio; requires --policy-config, --workspace, --run-root",
    )
    ap_stdio.add_argument("--document-id", default=None)
    ap_stdio.add_argument("--mode", choices=["docker", "seatbelt"], default="seatbelt")
    ap_stdio.add_argument("--docker-image", default="python:3.12-slim")
    ap_stdio.add_argument(
        "--jupyter-port",
        type=int,
        default=0,
        help="0=auto-pick free port",
    )
    ap_stdio.add_argument("--start-new-runtime", action="store_true")
    ap_stdio.add_argument("--trace-sandbox", action="store_true")
    ap_stdio.add_argument("--no-kernel-sandbox", action="store_true")
    ap_stdio.add_argument(
        "--debug-diag",
        action="store_true",
        help="Print child tool versions and paths for debugging",
    )
    ap_stdio.add_argument(
        "--policy-config",
        required=True,
        help="Path to sandboxer policy YAML (env.set/passthrough, fs.read_paths/write_paths, net.mode)",
    )
    ap_stdio.add_argument(
        "--workspace",
        required=True,
        help="Absolute path to Jupyter workspace root",
    )
    ap_stdio.add_argument(
        "--run-root",
        required=True,
        help="Absolute path for runtime/temp/logs",
    )
    ap_stdio.add_argument(
        "--kernel-python",
        default=os.environ.get("SJ_KERNEL_PYTHON", sys.executable),
        help="Python interpreter for the kernel (overrides SJ_KERNEL_PYTHON)",
    )

    args = ap.parse_args()

    if args.command == "stdio":
        raw = yaml.safe_load(Path(args.policy_config).read_text()) or {}
        try:
            policy = Policy(**raw)
        except Exception as e:
            print(f"Invalid policy YAML: {e}", file=sys.stderr)
            return 2
        env_set = dict(policy.env.set or {})
        env_passthrough = list(policy.env.passthrough or [])
        workspace = Path(args.workspace).resolve()
        run_root = Path(args.run_root).resolve()
        _ensure_dir(workspace)
        _ensure_dir(run_root)

        doc_id = _ensure_document_id(workspace, args.document_id)

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
            workspace=workspace,
            run_root=run_root,
            document_id=doc_id,
            start_new_runtime=args.start_new_runtime,
            jupyter_port=port,
            env_set=env_set,
            env_passthrough=env_passthrough,
            policy_yaml=Path(args.policy_config),
            trace=args.trace_sandbox,
            kernel_sandbox=not args.no_kernel_sandbox,
            kernel_python=args.kernel_python,
            debug_diag=args.debug_diag,
        )

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
