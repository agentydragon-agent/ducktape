import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import docker
import pytest

# MCP client imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _docker_client():
    return docker.from_env()


def _server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    pkg_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, **(extra or {})}
    candidates = [
        str(pkg_root / "src"),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join([c for c in candidates if c])
    return env


def _start_container(image: str = "alpine:3.20"):
    """Start a small container in the background for exec tests."""
    client = _docker_client()
    # Ensure image present
    try:
        client.images.pull(image)
    except Exception:
        # If offline, hope it's already present
        pass
    name = f"mcp-test-{uuid.uuid4().hex[:8]}"
    # Keep container alive for exec calls
    container = client.containers.run(
        image,
        ["sh", "-lc", "sleep 120"],
        name=name,
        detach=True,
        tty=False,
        stdin_open=False,
        auto_remove=True,
        working_dir="/",
    )
    # Give it a moment to get to running state
    for _ in range(20):
        container.reload()
        if container.status == "running":
            break
        time.sleep(0.1)
    return container


def _container_has_timeout(container) -> bool:
    try:
        exit_code, out = container.exec_run(
            ["sh", "-lc", "command -v timeout || which timeout"],
            demux=True,
        )
        if exit_code == 0:
            stdout = (out[0] or b"").decode()
            return bool(stdout.strip())
    except Exception:
        pass
    return False


def _extract_payload(resp):
    if getattr(resp, "structuredContent", None):
        return resp.structuredContent
    if hasattr(resp, "result") and isinstance(resp.result, dict):
        return resp.result
    raise AssertionError(f"Unexpected tool response shape: {resp!r}")


@pytest.fixture(scope="module")
def docker_exec_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    base_env = _server_env()
    # Ensure the subprocess sees the same Python environment as the test runner
    base_env["VIRTUAL_ENV"] = os.environ.get("VIRTUAL_ENV", "")
    return base_env


@asynccontextmanager
async def _session(env: dict[str, str]):
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "adgn_llm.mcp.docker_exec.launcher",
            "--image",
            env.get("DOCKER_IMAGE", "alpine:3.20"),
            "--describe",
        ],
        env=env,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _build_exec_args(cmd: list[str], timeout_secs: float | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"cmd": cmd}
    if timeout_secs is not None:
        payload["timeout_secs"] = timeout_secs
    return payload


async def _call_exec(session: ClientSession, cmd: list[str], timeout_secs: float | None = None):
    response = await session.call_tool(
        name="docker_exec",
        arguments=_build_exec_args(cmd, timeout_secs),
    )
    return _extract_payload(response)


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_hello_world(docker_exec_env: dict[str, str]):
    container = _start_container()
    try:
        server_env = {
            **docker_exec_env,
            "DOCKER_CONTAINER": container.id,
            "DOCKER_IMAGE": container.image.tags[0] if container.image.tags else container.image.id,
            "USE_CONTAINER_TIMEOUT_WRAPPER": "1" if _container_has_timeout(container) else "0",
        }

        async def run_session():
            async with _session(server_env) as session:
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert "docker_exec" in names

                payload = await _call_exec(session, ["/bin/echo", "hello"], timeout_secs=10)
                assert payload["exit_code"] == 0
                assert payload["timed_out"] is False
                assert "hello" in (payload["stdout"] or "")

        anyio.run(run_session)
    finally:
        try:
            container.kill()
        except Exception:
            pass


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_stderr_and_exit_code():
    container = _start_container()
    try:
        server_env = _server_env(
            {
                "DOCKER_CONTAINER": container.id,
                "DOCKER_IMAGE": container.image.tags[0] if container.image.tags else container.image.id,
                "USE_CONTAINER_TIMEOUT_WRAPPER": "0",  # not needed here
            }
        )

        async def run_session():
            async with _session(server_env) as session:
                payload = await _call_exec(
                    session,
                    cmd=["sh", "-lc", "echo err 1>&2; exit 3"],
                    timeout_secs=10,
                )
                assert payload["exit_code"] == 3
                assert "err" in (payload["stderr"] or "")

        anyio.run(run_session)
    finally:
        try:
            container.kill()
        except Exception:
            pass


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_timeout_flag():
    container = _start_container()
    try:
        has_timeout = _container_has_timeout(container)
        server_env = _server_env(
            {
                "DOCKER_CONTAINER": container.id,
                "USE_CONTAINER_TIMEOUT_WRAPPER": "1" if has_timeout else "0",
            }
        )

        async def run_session():
            async with _session(server_env) as session:
                payload = await _call_exec(session, ["sh", "-lc", "sleep 5"], timeout_secs=0.5)
                assert payload["timed_out"] is True
                # exit_code may be 124 with wrapper, or None without; allow common values
                assert payload.get("exit_code") in (None, 124, 143, 137, 1, 255)

        anyio.run(run_session)
    finally:
        try:
            container.kill()
        except Exception:
            pass
