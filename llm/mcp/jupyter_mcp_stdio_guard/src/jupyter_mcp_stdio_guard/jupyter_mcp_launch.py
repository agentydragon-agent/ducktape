#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_jupyter_server(
    *,
    workspace: Path,
    config_dir: Path,
    port: int,
    token: str,
    log_dir: Optional[Path],
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    # Honor explicit config dir (contains jupyter_server_config.py)
    # Jupyter honors JUPYTER_CONFIG_DIR; also pass --config to be explicit
    env.setdefault("JUPYTER_CONFIG_DIR", str(config_dir))

    cmd = [
        "jupyter",
        "server",
        "--port",
        str(port),
        "--ip",
        "127.0.0.1",
        "--ServerApp.root_dir",
        str(workspace),
        "--ServerApp.open_browser",
        "False",
        "--IdentityProvider.token",
        token,
        "--ServerApp.password",
        "",
        "--ServerApp.disable_check_xsrf",
        "True",
        "--config",
        str(config_dir / "jupyter_server_config.py"),
    ]

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        out_f = (log_dir / "jupyter_server.out").open("a", buffering=1)
        err_f = (log_dir / "jupyter_server.err").open("a", buffering=1)
    else:
        out_f = subprocess.DEVNULL  # type: ignore[assignment]
        err_f = subprocess.DEVNULL  # type: ignore[assignment]

    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=env)

    # Wait briefly for readiness
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                break
        except OSError:
            time.sleep(0.25)
    return proc


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="jupyter-mcp-launch",
        description="Launch Jupyter Server (unsandboxed) and jupyter-mcp-server (stdio) using precomposed config and kernels",
    )
    ap.add_argument("--config", required=True, help="Path to Jupyter config dir (contains jupyter_server_config.py)")
    ap.add_argument("--kernels", required=True, help="Path to kernels dir (kernelspecs)")
    ap.add_argument("--workspace", required=True, help="Absolute path to workspace (ServerApp.root_dir)")
    ap.add_argument("--kernel-name", default="python3", help="Default kernel name for new notebooks (hint)")
    ap.add_argument("--port", type=int, default=0, help="0 = auto-pick free port")
    ap.add_argument("--token", default="auto", help="'auto' to generate a token; or provide explicit token string")
    ap.add_argument("--start-new-runtime", action="store_true", help="Pass through to jupyter-mcp-server")
    ap.add_argument("--log-dir", default=None, help="Optional directory for Jupyter/MCP logs")
    args = ap.parse_args()

    config_dir = Path(args.config).resolve()
    kernels_dir = Path(args.kernels).resolve()
    workspace = Path(args.workspace).resolve()
    log_dir = Path(args.log_dir).resolve() if args.log_dir else None

    if not (config_dir / "jupyter_server_config.py").exists():
        print(f"jupyter-mcp-launch: config file not found: {config_dir / 'jupyter_server_config.py'}", file=sys.stderr)
        return 2
    if not kernels_dir.exists():
        print(f"jupyter-mcp-launch: kernels dir not found: {kernels_dir}", file=sys.stderr)
        return 2
    if not workspace.exists():
        print(f"jupyter-mcp-launch: workspace not found: {workspace}", file=sys.stderr)
        return 2

    # Ensure Jupyter sees only our kernels
    # Many setups configure this in the config file already; also export via env to be safe.
    child_env = {
        # Ensure our kernels dir is discoverable via JUPYTER_PATH (looks for <entry>/kernels/*)
        "JUPYTER_PATH": str(kernels_dir.parent),
        # Keep DATA_DIR pointing at the control root too (optional, aids paths/logs)
        "JUPYTER_DATA_DIR": str(kernels_dir.parent),
        "JUPYTER_CONFIG_DIR": str(config_dir),
    }

    # Write a minimal kernels.json to hint default
    if log_dir:
        (log_dir).mkdir(parents=True, exist_ok=True)
    runtime_dir = log_dir or (config_dir.parent / "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "kernels.json").write_text(f"{{\n  \"default\": \"{args.kernel_name}\"\n}}\n")

    port = args.port or _pick_free_port()
    token = secrets.token_urlsafe(24) if args.token == "auto" else args.token

    # Ensure we have jupyter and jupyter-mcp-server on PATH
    jup = shutil.which("jupyter") or ""
    jms = shutil.which("jupyter-mcp-server") or ""
    if not jup or not jms:
        print("jupyter-mcp-launch: 'jupyter' and/or 'jupyter-mcp-server' not found on PATH", file=sys.stderr)
        return 3

    print(f"[launch] jupyter @ http://127.0.0.1:{port} token=REDACTED", file=sys.stderr)

    jl = _start_jupyter_server(
        workspace=workspace,
        config_dir=config_dir,
        port=port,
        token=token,
        log_dir=log_dir,
        extra_env=child_env,
    )

    mcp_cmd = [
        "jupyter-mcp-server",
        "start",
        "--transport",
        "stdio",
        "--provider",
        "jupyter",
        "--document-url",
        f"http://127.0.0.1:{port}",
        "--document-id",
        ".mcp/auto.ipynb",
        "--document-token",
        token,
        "--runtime-url",
        f"http://127.0.0.1:{port}",
        "--runtime-token",
        token,
        "--start-new-runtime",
        "true" if args.start_new_runtime else "false",
    ]

    # Logs
    mcp_out = (log_dir / "mcp_stdout.log").open("ab", buffering=0) if log_dir else None
    mcp_err = (log_dir / "mcp_stderr.log").open("ab", buffering=0) if log_dir else None

    try:
        proc = subprocess.Popen(
            mcp_cmd,
            stdout=(mcp_out if mcp_out else None),
            stderr=(mcp_err if mcp_err else None),
        )
        return proc.wait()
    finally:
        try:
            jl.terminate()
        except Exception:
            pass
        try:
            jl.wait(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
