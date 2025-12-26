"""Test fixtures for mcp_infra tests."""

import pytest

from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.testing.fixtures import make_container_opts

# Register mcp_infra and agent_core fixtures
pytest_plugins = ["mcp_infra.testing.fixtures", "agent_core.testing.fixtures"]


@pytest.fixture
async def docker_exec_server_py312slim(async_docker_client):
    """Canonical Docker exec server using python:3.12-slim image."""
    opts = make_container_opts("python:3.12-slim")
    return ContainerExecServer(async_docker_client, opts)


@pytest.fixture
async def typed_docker_client(make_typed_mcp, docker_exec_server_py312slim):
    """Typed MCP client for docker exec server with python:3.12-slim.

    Yields (TypedClient, session) tuple for direct use in tests.
    """
    async with make_typed_mcp(docker_exec_server_py312slim) as (client, session):
        yield client, session
