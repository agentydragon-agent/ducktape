from __future__ import annotations

import sys

from fastmcp.client import Client
from fastmcp.client.messages import MessageHandler
from fastmcp.mcp_config import StdioMCPServer
from fastmcp.server import FastMCP
from mcp import types
import pytest

from adgn.mcp.compositor.clients import CompositorAdminClient
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.mcp.resources.clients import ResourcesClient
from adgn.mcp.resources.server import make_resources_server
from tests.util.notifications import SubscriptionRecorder, enable_resources_caps, install_subscription_recorder


class ResourceUpdatedCapture(MessageHandler):
    """MessageHandler that captures resource updated notifications."""

    def __init__(self) -> None:
        self.updated: list[str] = []

    async def on_resource_updated(self, message: types.ResourceUpdatedNotification) -> None:  # type: ignore[override]
        self.updated.append(str(message.params.uri))


@pytest.fixture
def resource_capture() -> ResourceUpdatedCapture:
    """Fresh ResourceUpdatedCapture instance for each test."""
    return ResourceUpdatedCapture()


@pytest.fixture
def stdio_echo_spec() -> StdioMCPServer:
    """Launch packaged echo server module via -m as a stdio spec."""
    return StdioMCPServer(command=sys.executable, args=["-m", "adgn.mcp.testing.stdio_app"])


# Note: `compositor` fixture is defined in top-level tests/conftest.py


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
        await mount_standard_inproc_servers(compositor=comp, mount_resources=False)
        admin = CompositorAdminClient(client)
        yield admin, comp


@pytest.fixture
def origin_with_recorder() -> tuple[FastMCP, SubscriptionRecorder]:
    """Origin server with subscription recorder attached."""
    m = NotifyingFastMCP("origin")
    recorder = install_subscription_recorder(m)

    @m.resource("resource://foo/bar", name="dummy", mime_type="text/plain", description="dummy")
    async def foo_bar() -> str:
        return "ok"

    # Ensure this origin advertises resources.subscribe for gating and
    # registers explicit handlers so subscribe/unsubscribe calls succeed.
    enable_resources_caps(m, subscribe=True)
    return m, recorder


# Note: backend_server fixture is provided by tests/conftest.py (uses make_simple_mcp)
