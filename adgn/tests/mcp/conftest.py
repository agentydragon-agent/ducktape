from __future__ import annotations

import sys

from fastmcp.client import Client
from fastmcp.mcp_config import StdioMCPServer
import pytest

from adgn.mcp.compositor.clients import CompositorAdminClient
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.resources.clients import ResourcesClient
from adgn.mcp.resources.server import make_resources_server


@pytest.fixture
def stdio_echo_spec() -> StdioMCPServer:
    """Launch packaged echo server module via -m as a stdio spec."""
    return StdioMCPServer(command=sys.executable, args=["-m", "adgn.mcp.testing.stdio_app"])


@pytest.fixture(scope="function")
async def compositor():
    """Fresh Compositor instance for each test.

    No explicit cleanup - compositor will be garbage collected after test completes.
    """
    return Compositor("comp")


@pytest.fixture
async def compositor_client(compositor):
    """Client connected to the compositor."""
    async with Client(compositor) as client:
        yield client


@pytest.fixture
async def resources_server(compositor):
    """Resources server for the compositor."""
    return make_resources_server(compositor=compositor)


@pytest.fixture
async def resources_client(resources_server):
    """Client for the resources server."""
    async with Client(resources_server) as client:
        yield client


@pytest.fixture
async def typed_resources_client(resources_client):
    """Typed ResourcesClient wrapping the resources server client."""
    return ResourcesClient(resources_client)


@pytest.fixture
async def admin_env(make_compositor):
    """Compositor with standard admin/meta servers and an admin client.

    Yields a tuple (admin_client, compositor).
    """
    async with make_compositor({}) as (client, comp):
        await mount_standard_inproc_servers(compositor=comp, gateway_client=None)
        admin = CompositorAdminClient(client)
        yield admin, comp


@pytest.fixture
async def resources_env(compositor, compositor_client, resources_server, resources_client):
    """Compositor + resources server mounted using a real gateway client.

    Yields (ResourcesClient, Compositor) so tests can mount origins and use the
    typed resources client to subscribe/unsubscribe and read the index.
    """
    yield ResourcesClient(resources_client), compositor
