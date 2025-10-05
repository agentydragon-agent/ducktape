from __future__ import annotations

import contextlib
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import IO, Any, Iterator

import pytest


def _read_line_json(inp: IO[bytes] | None, timeout: float | None = None) -> dict[str, Any] | None:
    assert inp is not None
    if timeout is None or timeout <= 0:
        line = inp.readline()
        if not line:
            return None
        try:
            import json

            return json.loads(line.decode())
        except Exception:
            return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = inp.readline()
        if line:
            try:
                import json

                return json.loads(line.decode())
            except Exception:
                return None
        time.sleep(0.05)
    return None


@pytest.fixture
def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def pkg_src_env_update() -> dict[str, str]:
    src_dir = Path(__file__).resolve().parents[3] / "src"
    env: dict[str, str] = {
        "PYTHONPATH": str(src_dir),
        "JUPYTER_LOG_LEVEL": "DEBUG",
    }
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
        argv = [
            os.fspath(x) if hasattr(x, "__fspath__") else (x if isinstance(x, str) else str(x))
            for x in cmd
        ]
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
            if mode:
                argv = runner + [mode] + argv[1:]
            else:
                argv = runner + argv[1:]
        run_root: Path | None = None
        if "--run-root" in argv:
            idx = argv.index("--run-root")
            if idx + 1 < len(argv):
                run_root = Path(argv[idx + 1])
                os.environ["SJ_TEST_RUN_ROOT"] = str(run_root)
        env = os.environ.copy()
        if env_update:
            env.update(env_update)
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            yield proc
        finally:
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)

    return _run


@pytest.fixture
def mcp_stdio_protocol():
    def _call(
        stdin: IO[bytes] | None,
        stdout: IO[bytes] | None,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        import json

        init_id = secrets.randbelow(10000) + 1
        init = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "pytest", "version": "0.0.1"},
            },
        }
        assert stdin is not None
        stdin.write((json.dumps(init) + "\n").encode())
        stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = _read_line_json(stdout, 1.0)
            if m and m.get("id") == init_id and ("result" in m or "error" in m):
                break
        stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
        )
        stdin.flush()
        time.sleep(0.2)
        call_id = secrets.randbelow(10000) + 1
        call = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        stdin.write((json.dumps(call) + "\n").encode())
        stdin.flush()
        result = None
        deadline = time.time() + timeout
        while time.time() < deadline and not result:
            m = _read_line_json(stdout, 1.0)
            if m and m.get("id") == call_id and ("result" in m or "error" in m):
                result = m
        assert result is not None, "tool call timed out"
        return result

    return _call


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
