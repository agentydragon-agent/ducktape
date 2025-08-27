#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

# Seatbelt base policy for macOS sandbox-exec.
# NOTE: Intentionally DOES NOT grant global read anymore.
SANDBOX_POLICY_BASE = """
(version 1)
(deny default)

;; Process primitives
(allow process*)
(allow signal (target self))

;; File/device basics
(allow file* (literal "/dev/null"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file* (subpath "/dev/tty"))

;; IPC and system lookups used by Python/stdlib
(allow ipc-posix-shm)
(allow ipc-posix-sem)
(allow ipc-sysv-shm)
(allow mach-lookup)
(allow system-socket)
(allow sysctl-read)

;; Networking defaults (subject to future tightening)
(allow network-outbound)
(allow network-inbound (local ip))
"""


class PolicyConfig(BaseModel):
    # Explicit, zero-magic authz spec
    allow_read_all: bool = False
    allow_write_all: bool = False
    read_paths: list[str] = Field(default_factory=list)
    write_paths: list[str] = Field(default_factory=list)

    # Environment injection
    env: dict[str, str] = Field(default_factory=dict)
    env_passthrough: list[str] = Field(default_factory=list)

    # Present for future use; currently not enforced
    net: str | None = None  # TODO: implement (none|loopback|all|allowlist:...|proxy:...)

    class Config:
        extra = "forbid"  # hard break on unknown fields

    @model_validator(mode="after")
    def _validate_compat(self) -> "PolicyConfig":
        if self.allow_read_all and self.read_paths:
            raise ValueError("allow_read_all=true is incompatible with non-empty read_paths")
        if self.allow_write_all and self.write_paths:
            raise ValueError("allow_write_all=true is incompatible with non-empty write_paths")
        # Write implies read: disallow combining allow_write_all with read_paths to avoid redundancy
        if self.allow_write_all and self.read_paths:
            raise ValueError("allow_write_all=true implies read; read_paths must be empty when allow_write_all is set")
        return self


# Utilities

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _ensure_document_id(workspace: Path, document_id: str | None) -> str:
    if document_id:
        p = workspace / document_id
    else:
        rel = (
            Path(".mcp")
            / "scratch"
            / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4) + ".ipynb")
        )
        p = workspace / rel
        document_id = str(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f"Notebook already exists: {p}")
    kernelspec = {"name": "python3", "display_name": "Python 3", "language": "python"}
    p.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "kernelspec": kernelspec,
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        )
    )
    return document_id  # type: ignore[return-value]


# Docker mode helper (unchanged behavior aside from workspace/run_root coming from CLI)

def _build_bash_script(workspace: Path, document_id: str, token: str, start_new_runtime: bool) -> str:
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
    bash_script = _build_bash_script(Path("/workspace"), document_id, token, start_new_runtime)
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


# Jupyter helpers

def _kernels_dir(run_root: Path) -> Path:
    return run_root / "data" / "kernels"


def _write_sandboxed_kernelspec(
    run_root: Path,
    workspace: Path,
    policy_path: Path,
    kernel_python: str,
) -> None:
    # Override the default 'python3' kernel to ensure the sandbox is used.
    ks_dir = _kernels_dir(run_root) / "python3"
    ks_dir.mkdir(parents=True, exist_ok=True)
    kernel_json = {
        "argv": [
            "env",
            "SJ_KERNEL_SANDBOXED=1",
            f"SJ_POLICY_PATH={policy_path}",
            "sandbox-exec",
            "-f",
            str(policy_path),
            kernel_python,
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "display_name": "Python 3",
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
    cfg: PolicyConfig,
    trace: bool = True,
    kernel_sandbox: bool = True,
    kernel_python: str,
    debug_diag: bool = False,
) -> int:
    token = secrets.token_urlsafe(24)
    for sub in ("runtime", "data", "config", "mpl", "pycache", "cache", "tmp"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    policy_path = run_root / "policy.sb"

    # Compose final policy from explicit spec
    dyn_lines: list[str] = []
    if trace:
        dyn_lines.append(f'(trace "{(run_root / "profile.sb")!s}")')

    # Writes
    if cfg.allow_write_all:
        dyn_lines.append('(allow file* (subpath "/"))')
    else:
        for p in (cfg.write_paths or []):
            dyn_lines.append(f'(allow file* (subpath "{Path(p).resolve()}") )')

    # Reads
    if cfg.allow_write_all:
        # write implies read; no extra read rules needed
        pass
    elif cfg.allow_read_all:
        dyn_lines.append('(allow file-read* (subpath "/"))')
    else:
        for p in (cfg.read_paths or []):
            dyn_lines.append(f'(allow file-read* (subpath "{Path(p).resolve()}") )')

    policy_text = SANDBOX_POLICY_BASE + "\n" + "\n".join(dyn_lines) + "\n"
    policy_path.write_text(policy_text)

    if kernel_sandbox:
        _write_sandboxed_kernelspec(run_root, workspace, policy_path, kernel_python=kernel_python)
        # Ensure newly created notebooks default to the sandboxed kernel
        (run_root / "runtime" / "kernels.json").write_text(json.dumps({"default": "python3"}))

    print(f"[wrapper] run_root={run_root!s} workspace={workspace!s}", file=sys.stderr, flush=True)
    print(
        f"[wrapper] jupyter: http://127.0.0.1:{jupyter_port} token=REDACTED",
        file=sys.stderr,
        flush=True,
    )
    if trace:
        print(
            f"[seatbelt] Sandbox trace enabled. policy_path={policy_path!s} trace={(run_root / 'profile.sb')!s}",
            file=sys.stderr,
            flush=True,
        )

    # Child environment: explicit env + passthrough + defaults for Jupyter dirs
    child_env: dict[str, str] = dict(cfg.env or {})
    for k in cfg.env_passthrough or []:
        if k in os.environ:
            child_env[k] = os.environ[k]
    # Intentionally do not default Jupyter dirs here; provide via cfg.env if desired

    # Diagnostics: print child toolchain versions and paths (behind flag/env)
    if debug_diag or os.environ.get("SJ_DEBUG_DIAG"):
        def _run_out(args: list[str]) -> str:
            try:
                cp = subprocess.run(args, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                return cp.stdout.strip()
            except Exception as e:  # noqa: BLE001
                return f"<error: {e}>"
        try:
            child_path = child_env.get("PATH", os.environ.get("PATH", ""))
            jup_path = shutil.which("jupyter", path=child_path) or "<not found>"
            jms_path = shutil.which("jupyter-mcp-server", path=child_path) or "<not found>"
            print(f"[diag] child PATH={child_path}", file=sys.stderr)
            print(f"[diag] which jupyter -> {jup_path}", file=sys.stderr)
            print(f"[diag] jupyter --version ->\n{_run_out(['jupyter', '--version'])}", file=sys.stderr)
            print(f"[diag] jupyter server --version ->\n{_run_out(['jupyter', 'server', '--version'])}", file=sys.stderr)
            print(f"[diag] which jupyter-mcp-server -> {jms_path}", file=sys.stderr)
            _jms_help = _run_out(['jupyter-mcp-server', '--help'])
            print(f"[diag] jupyter-mcp-server --help (head) ->\n{_jms_help.splitlines()[0] if _jms_help else ''}", file=sys.stderr)
            print(f"[diag] parent python={sys.executable} {sys.version.split()[0]}", file=sys.stderr)
            kp_out = _run_out([kernel_python, '--version'])
            print(f"[diag] kernel python={kernel_python} -> {kp_out}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[diag] version diagnostics failed: {e}", file=sys.stderr)

    # Write a server config to prefer our kernels only
    (run_root / "config").mkdir(parents=True, exist_ok=True)
    (run_root / "config" / "jupyter_server_config.py").write_text(
        "\n".join(
            [
                "c = get_config()",
                f"c.KernelSpecManager.kernel_dirs = ['{_kernels_dir(run_root)!s}']",
                "c.KernelSpecManager.ensure_native_kernel = False",
                # Avoid default_kernel_name trait to prevent notebook_shim errors
                "c.ServerApp.open_browser = False",
                "c.ServerApp.ip = '127.0.0.1'",
                "c.ServerApp.disable_check_xsrf = True",
            ]
        )
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
        raise FileNotFoundError("jupyter-mcp-server not found on PATH (checked child env)")
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

    async def _run_mcp_async() -> int:
        proc = await asyncio.create_subprocess_exec(
            *mcp_cmd,
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        f_out = mcp_stdout_path.open("ab", buffering=0)
        f_err = mcp_stderr_path.open("ab", buffering=0)

        async def _pump(reader: asyncio.StreamReader, file_obj, buffer):
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                try:
                    buffer.write(chunk)
                    buffer.flush()
                except (BrokenPipeError, ValueError) as e:
                    print(f"[wrapper] tee write to parent failed: {e}", file=sys.stderr)
                try:
                    file_obj.write(chunk)
                    file_obj.flush()
                except OSError as e:
                    print(f"[wrapper] tee write to log failed: {e}", file=sys.stderr)

        try:
            t1 = asyncio.create_task(_pump(proc.stdout, f_out, sys.stdout.buffer))  # type: ignore[arg-type]
            t2 = asyncio.create_task(_pump(proc.stderr, f_err, sys.stderr.buffer))  # type: ignore[arg-type]
            rc = await proc.wait()
            await asyncio.gather(t1, t2)
            return rc
        finally:
            try:
                f_out.close()
            except Exception:
                pass
            try:
                f_err.close()
            except Exception:
                pass
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

    try:
        return asyncio.run(_run_mcp_async())
    finally:
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
    ap_stdio.add_argument("--jupyter-port", type=int, default=0, help="0=auto-pick free port")
    ap_stdio.add_argument("--start-new-runtime", action="store_true")
    ap_stdio.add_argument("--trace-sandbox", action="store_true")
    ap_stdio.add_argument("--no-kernel-sandbox", action="store_true")
    ap_stdio.add_argument("--debug-diag", action="store_true", help="Print child tool versions and paths for debugging")
    ap_stdio.add_argument(
        "--policy-config",
        required=True,
        help="Path to YAML policy config (allow_read_all, allow_write_all, read_paths, write_paths, env, env_passthrough)",
    )
    ap_stdio.add_argument("--workspace", required=True, help="Absolute path to Jupyter workspace root")
    ap_stdio.add_argument("--run-root", required=True, help="Absolute path for runtime/temp/logs")
    ap_stdio.add_argument(
        "--kernel-python",
        default=os.environ.get("SJ_KERNEL_PYTHON", sys.executable),
        help="Python interpreter for the kernel (overrides SJ_KERNEL_PYTHON)",
    )

    args = ap.parse_args()

    if args.command == "stdio":
        cfg = PolicyConfig(**yaml.safe_load(Path(args.policy_config).read_text()))
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
            return _docker(workspace, doc_id, args.docker_image, args.start_new_runtime, port)

        return _seatbelt(
            workspace=workspace,
            run_root=run_root,
            document_id=doc_id,
            start_new_runtime=args.start_new_runtime,
            jupyter_port=port,
            cfg=cfg,
            trace=args.trace_sandbox,
            kernel_sandbox=not args.no_kernel_sandbox,
            kernel_python=args.kernel_python,
            debug_diag=args.debug_diag,
        )

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
