from __future__ import annotations

import pytest

from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.exec.models import Exited, TimedOut, make_exec_input
from tests.conftest import make_container_opts


@pytest.fixture
def exec_server(async_docker_client):
    """Container exec server for docker exec tests."""
    return ContainerExecServer(async_docker_client, make_container_opts("python:3.12-slim"))


@pytest.fixture
async def exec_client(make_typed_mcp, exec_server):
    async with make_typed_mcp(exec_server) as (client, _session):
        yield client


@pytest.mark.requires_docker
async def test_exec_stdout_stderr_timeout(exec_client) -> None:
    # stdout
    r1 = await exec_client.exec(make_exec_input(["/bin/echo", "hello"], timeout_ms=5000))
    assert r1.exit == Exited(exit_code=0)
    assert isinstance(r1.stdout, str)  # Short output should not be truncated
    assert r1.stdout == "hello\n"
    # stderr and nonzero exit
    r2 = await exec_client.exec(make_exec_input(["sh", "-lc", "echo err 1>&2; exit 3"], timeout_ms=5000))
    assert r2.exit == Exited(exit_code=3)
    assert "err" in (r2.stderr or "")
    # timeout
    r3 = await exec_client.exec(make_exec_input(["sh", "-lc", "sleep 5"], timeout_ms=500))
    assert r3.exit == TimedOut()


@pytest.mark.requires_docker
async def test_persession_exec_timeout_then_next_ok(exec_client) -> None:
    # Force timeout
    t1 = await exec_client.exec(make_exec_input(["sh", "-lc", "sleep 3"], timeout_ms=500))
    assert t1.exit == TimedOut()
    # Next call should succeed after restart
    r1 = await exec_client.exec(make_exec_input(["/bin/echo", "ok"], timeout_ms=5000))
    assert r1.exit == Exited(exit_code=0)
    assert isinstance(r1.stdout, str)  # Short output should not be truncated
    assert r1.stdout == "ok\n"
