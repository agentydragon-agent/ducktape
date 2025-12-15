from __future__ import annotations

import sys

from fastmcp.client import Client
from fastmcp.client.messages import MessageHandler
from fastmcp.mcp_config import StdioMCPServer
from fastmcp.server import FastMCP
from mcp import types
from pydantic import AnyUrl
import pytest

from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.resources.server import ResourcesServer
from adgn.mcp.testing.resources_stubs import ResourcesServerStub
from tests.util.notifications import SubscriptionRecorder, enable_resources_caps, install_subscription_recorder


class ResourceUpdatedCapture(MessageHandler):
    """MessageHandler that captures resource updated notifications."""

    def __init__(self) -> None:
        self.updated: list[AnyUrl] = []

    async def on_resource_updated(self, message: types.ResourceUpdatedNotification) -> None:  # type: ignore[override]
        self.updated.append(message.params.uri)


@pytest.fixture
def resource_capture() -> ResourceUpdatedCapture:
    """Fresh ResourceUpdatedCapture instance for each test."""
    return ResourceUpdatedCapture()


@pytest.fixture
def stdio_echo_spec() -> StdioMCPServer:
    """Launch packaged echo server module via -m as a stdio spec."""
    return StdioMCPServer(command=sys.executable, args=["-m", "adgn.mcp.testing.stdio_app"])


# Note: `compositor` fixture is defined in top-level tests/conftest.py
# Note: `mock_registry` fixture is defined in top-level tests/conftest.py


# Note: compositor_client fixture is provided in tests/conftest.py


@pytest.fixture
async def resources_server(compositor):
    """Resources server for the compositor."""

    return ResourcesServer(compositor=compositor)


@pytest.fixture
async def resources_client(resources_server):
    """Client for the resources server."""
    async with Client(resources_server) as client:
        yield client


@pytest.fixture
async def typed_resources_client(resources_server, resources_client):
    """Typed stub for the resources server."""
    return ResourcesServerStub.from_server(resources_server, resources_client)


@pytest.fixture
def origin_with_recorder() -> tuple[FastMCP, SubscriptionRecorder]:
    """Origin server with subscription recorder attached."""
    m = EnhancedFastMCP("origin")
    recorder = install_subscription_recorder(m)

    @m.resource("resource://foo/bar", name="dummy", mime_type="text/plain", description="dummy")
    async def foo_bar() -> str:
        return "ok"

    # Ensure this origin advertises resources.subscribe for gating and
    # registers explicit handlers so subscribe/unsubscribe calls succeed.
    enable_resources_caps(m, subscribe=True)
    return m, recorder


# Note: make_simple_mcp fixture is provided by tests/conftest.py (uses make_make_simple_mcp)
