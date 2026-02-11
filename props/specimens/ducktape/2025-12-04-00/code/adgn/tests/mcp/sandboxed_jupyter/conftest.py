from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import socket
import sys

from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
import pytest

from tests._markers import REQUIRES_SANDBOX_EXEC
from tests.mcp.sandboxed_jupyter.policy_fixture import write_policy

pytestmark = [*REQUIRES_SANDBOX_EXEC, pytest.mark.shell]


@pytest.fixture
def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def pkg_src_env_update() -> dict[str, str]:
    src_dir = Path(__file__).resolve().parents[3] / "src"
    env: dict[str, str] = {"PYTHONPATH": str(src_dir), "JUPYTER_LOG_LEVEL": "DEBUG"}
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"] = f"{src_dir}:{os.environ['PYTHONPATH']}"
    return env


@pytest.fixture
def mcp_client_from_cmd(pkg_src_env_update):
    """Create a FastMCP client from a command and arguments.

    Returns an async context manager that yields the initialized client.
    """

    @asynccontextmanager
    async def _create(command: str, args: list[str], *, env: dict[str, str] | None = None, init_timeout: float = 30.0):
        # Handle sandbox-jupyter command specially
        if command == "sandbox-jupyter":
            # Use Python module invocation instead
            command = sys.executable
            args = ["-m", "adgn.mcp.sandboxed_jupyter.wrapper", *args]

        # Merge environment updates
        final_env = os.environ.copy()
        if pkg_src_env_update:
            final_env.update(pkg_src_env_update)
        if env:
            final_env.update(env)

        transport = StdioTransport(
            command=command,
            args=args,
            env=final_env,
            keep_alive=False,  # Don't keep subprocess alive after test
        )

        async with Client(transport) as client:
            # Initialize the client
            await asyncio.wait_for(client.initialize(), timeout=init_timeout)
            yield client

    return _create


# --- Workspace provisioning for wrapper smoke tests ---


@pytest.fixture
def provision_ws_with_policy(tmp_path: Path):
    """Create a workspace and run_root with a usable sandbox policy file.

    Writes .sandbox_jupyter.yaml under the workspace using a permissive but
    OS-stable policy (read: '/', write: run_root/ws), loopback-only net.
    Returns (workspace_path, run_root_path).
    """
    ws = tmp_path / "ws"
    run_root = tmp_path / "run_root"
    ws.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    # Prefer a permissive read to reduce macOS dyld fragility in CI/local
    write_policy(
        ws,
        run_root,
        allow_read_all=True,
        allow_write_all=None,
        add_read_paths=None,
        add_write_paths=None,
        env_set=None,
        env_passthrough=None,
        net="loopback",
    )
    return ws, run_root
