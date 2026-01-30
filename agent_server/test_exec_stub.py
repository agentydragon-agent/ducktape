"""Docker exec stub test — pure container exec roundtrip, no OpenAI."""

from __future__ import annotations

import pytest
import pytest_bazel

from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.models import BaseExecResult, Exited, make_exec_input
from mcp_infra.naming import build_mcp_function
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.stubs.typed_stubs import ToolStub
from mcp_infra.testing.fixtures import make_container_opts

ECHO_CMD = ["/bin/echo", "-n", "hello"]
SERVER_NAME = MCPMountPrefix("box")


@pytest.fixture
async def docker_exec_server_py312slim(async_docker_client, python_slim_image):
    """Canonical Docker exec server using python-slim image."""
    opts = make_container_opts(python_slim_image)
    return ContainerExecServer(async_docker_client, opts)


@pytest.fixture
async def mcp_client_box(docker_exec_server_py312slim, compositor, compositor_client):
    """MCP client with box Docker exec server (no policy gateway)."""
    await compositor.mount_inproc(MCPMountPrefix("box"), docker_exec_server_py312slim)
    return compositor_client


async def _assert_exec_echo(sess) -> None:
    stub = ToolStub(sess, build_mcp_function(SERVER_NAME, "exec"), BaseExecResult)
    res = await stub(make_exec_input(ECHO_CMD))
    assert isinstance(res.exit, Exited)
    assert res.exit.exit_code == 0
    assert (res.stdout or "") == "hello"
    assert (res.stderr or "") == ""


@pytest.mark.requires_docker
async def test_exec_roundtrip_echo(mcp_client_box) -> None:
    """Spin up real Docker container and roundtrip an echo via exec without policy gateway."""
    await _assert_exec_echo(mcp_client_box)


if __name__ == "__main__":
    pytest_bazel.main()
