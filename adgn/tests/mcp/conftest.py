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
async def resources_env():
    """Compositor + resources server mounted using a real gateway client.

    Yields (ResourcesClient, Compositor) so tests can mount origins and use the
    typed resources client to subscribe/unsubscribe and read the index.
    """
    comp = Compositor("comp")
    async with Client(comp) as gw:
        res_server = make_resources_server(compositor=comp)
        async with Client(res_server) as res_client:
            yield ResourcesClient(res_client), comp
