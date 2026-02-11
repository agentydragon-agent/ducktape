#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from typing import IO

from adgn.util.net import wait_for_port

StrPath = str | os.PathLike[str]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = int(s.getsockname()[1])
        return port


def _start_jupyter_server(
    *,
    workspace: Path,
    config_dir: Path,
    port: int,
    token: str,
    log_dir: Path | None,
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

    out_f: IO[str] | int
    err_f: IO[str] | int
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        out_f = (log_dir / "jupyter_server.out").open("a", buffering=1)
        err_f = (log_dir / "jupyter_server.err").open("a", buffering=1)
    else:
        out_f = subprocess.DEVNULL
        err_f = subprocess.DEVNULL

    proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=env)

    # Wait for readiness (up to 12s)
    wait_for_port("127.0.0.1", port, timeout_secs=12.0)
    return proc


def run_jupyter_mcp(
    *,
    config_dir: StrPath,
    kernels_dir: StrPath,
    workspace: StrPath,
    kernel_name: str = "python3",
    port: int = 0,
    token: str = "auto",
    start_new_runtime: bool = False,
    log_dir: StrPath | None = None,
) -> int:
    """Programmatic entrypoint that accepts str or Path-like arguments."""
    config_dir = Path(config_dir).resolve()
    kernels_dir = Path(kernels_dir).resolve()
    workspace = Path(workspace).resolve()
    log_dir_path = Path(log_dir).resolve() if log_dir else None

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
    child_env = {
        "JUPYTER_PATH": str(kernels_dir.parent),
        "JUPYTER_DATA_DIR": str(kernels_dir.parent),
        "JUPYTER_CONFIG_DIR": str(config_dir),
    }

    # Write a minimal kernels.json to hint default
    runtime_dir = log_dir_path or (config_dir.parent / "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "kernels.json").write_text(json.dumps({"default": kernel_name}) + "\n")

    eff_port = port or _pick_free_port()
    eff_token = secrets.token_urlsafe(24) if token == "auto" else token

    # Ensure we have jupyter and jupyter-mcp-server on PATH
    if not (shutil.which("jupyter") and shutil.which("jupyter-mcp-server")):
        print("jupyter-mcp-launch: 'jupyter' and/or 'jupyter-mcp-server' not found on PATH", file=sys.stderr)
        return 3

    from urllib.parse import urlunparse

    jpy_url = urlunparse(("http", f"127.0.0.1:{eff_port}", "", "", "", ""))
    print(f"[launch] jupyter @ {jpy_url} token=REDACTED", file=sys.stderr)

    jl = _start_jupyter_server(
        workspace=workspace,
        config_dir=config_dir,
        port=eff_port,
        token=eff_token,
        log_dir=log_dir_path,
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
        jpy_url,
        "--document-id",
        ".mcp/auto.ipynb",
        "--document-token",
        eff_token,
        "--runtime-url",
        jpy_url,
        "--runtime-token",
        eff_token,
        "--start-new-runtime",
        "true" if start_new_runtime else "false",
    ]

    try:
        proc = subprocess.Popen(mcp_cmd)
        return proc.wait()
    finally:
        with contextlib.suppress(Exception):
            jl.terminate()
        with contextlib.suppress(Exception):
            jl.wait(timeout=5)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="jupyter-mcp-launch",
        description=(
            "Launch Jupyter Server (unsandboxed) and jupyter-mcp-server (stdio) using precomposed config and kernels"
        ),
    )
    ap.add_argument(
        "--config", required=True, type=Path, help="Path to Jupyter config dir (contains jupyter_server_config.py)"
    )
    ap.add_argument("--kernels", required=True, type=Path, help="Path to kernels dir (kernelspecs)")
    ap.add_argument("--workspace", required=True, type=Path, help="Absolute path to workspace (ServerApp.root_dir)")
    ap.add_argument("--kernel-name", default="python3", help="Default kernel name for new notebooks (hint)")
    ap.add_argument("--port", type=int, default=0, help="0 = auto-pick free port")
    ap.add_argument("--token", default="auto", help="'auto' to generate a token; or provide explicit token string")
    ap.add_argument("--start-new-runtime", action="store_true", help="Pass through to jupyter-mcp-server")
    ap.add_argument("--log-dir", default=None, type=Path, help="Optional directory for Jupyter/MCP logs")
    args = ap.parse_args()
    return run_jupyter_mcp(
        config_dir=args.config,
        kernels_dir=args.kernels,
        workspace=args.workspace,
        kernel_name=args.kernel_name,
        port=args.port,
        token=args.token,
        start_new_runtime=bool(args.start_new_runtime),
        log_dir=args.log_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
