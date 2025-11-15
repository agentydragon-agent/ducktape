from __future__ import annotations

from collections.abc import Iterator
import contextlib
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys

from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
import pytest
from tests._markers import REQUIRES_SANDBOX_EXEC

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
def launch_proc(tmp_path: Path):
    @contextmanager
    def _run(
        cmd: list[str | os.PathLike[str] | int], *, env_update: dict[str, str] | None = None
    ) -> Iterator[subprocess.Popen]:
        # Normalize argv to strings, allowing PathLike and ints transparently
        argv = [os.fspath(x) if hasattr(x, "__fspath__") else (x if isinstance(x, str) else str(x)) for x in cmd]
        if argv and str(argv[0]) == "sandbox-jupyter":
            mode = None
            if "--mode" in argv:
                i = argv.index("--mode")
                mode = argv[i + 1] if i + 1 < len(argv) else None
                del argv[i : i + 2]
            for flag in ("--trace-sandbox", "--no-kernel-sandbox"):
                if flag in argv:
                    argv.remove(flag)
            runner = [sys.executable, "-m", "adgn.mcp.sandboxed_jupyter.wrapper"]
            argv = runner + [mode] + argv[1:] if mode else runner + argv[1:]
        run_root: Path | None = None
        if "--run-root" in argv:
            idx = argv.index("--run-root")
            if idx + 1 < len(argv):
                run_root = Path(argv[idx + 1])
                os.environ["SJ_TEST_RUN_ROOT"] = str(run_root)
        env = os.environ.copy()
        if env_update:
            env.update(env_update)
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            yield proc
        finally:
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)

    return _run


@pytest.fixture
def mcp_client_from_cmd(pkg_src_env_update):
    """Create a FastMCP client from a command and arguments.

    Returns an async context manager that yields the initialized client.
    """
    import asyncio
    from contextlib import asynccontextmanager
    import sys

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
    from .policy_fixture import write_policy

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
