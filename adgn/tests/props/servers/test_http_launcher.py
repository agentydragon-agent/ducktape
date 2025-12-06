"""Tests for the ephemeral MCP HTTP server launcher.

Tests lifecycle management, port allocation, and basic connectivity.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
import httpx
import pytest

from adgn.mcp.testing.simple_servers import build_simple_tools
from adgn.props.servers.http_launcher import ServerHandle, launch_mcp_http_server


def _create_test_server(token: str) -> FastMCP:
    """Create a minimal FastMCP server with auth for testing."""
    auth = StaticTokenVerifier(tokens={token: {"client_id": "test", "scopes": []}})
    server = FastMCP("test_server", auth=auth, instructions="Test server for HTTP launcher tests.")
    build_simple_tools(server)
    return server


@pytest.fixture
async def server_handle() -> AsyncIterator[ServerHandle]:
    """Launch a test HTTP server and yield the handle."""
    async with launch_mcp_http_server(_create_test_server, container_host="localhost") as handle:
        yield handle


@pytest.fixture
def http_client() -> httpx.AsyncClient:
    """Create an httpx async client."""
    return httpx.AsyncClient()


class TestLaunchMcpHttpServer:
    """Tests for launch_mcp_http_server context manager."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self, server_handle: ServerHandle):
        """Server should start, be reachable, and stop cleanly."""
        assert isinstance(server_handle, ServerHandle)
        assert server_handle.port > 0
        assert server_handle.token  # Non-empty token
        assert "host.docker.internal" in server_handle.url

        # Server should be reachable
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{server_handle.port}/",
                headers={"Authorization": f"Bearer {server_handle.token}"},
                timeout=5.0,
            )
            # MCP servers may return various status codes, but should respond
            assert response.status_code in (200, 404, 405)

    @pytest.mark.asyncio
    async def test_server_stops_after_context(self):
        """Server should stop after context manager exits."""
        async with launch_mcp_http_server(_create_test_server, container_host="localhost") as handle:
            port = handle.port

        # Give it a moment to fully shut down
        await asyncio.sleep(0.2)
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(f"http://127.0.0.1:{port}/", timeout=1.0)

    @pytest.mark.asyncio
    async def test_auth_rejects_missing_token(self, server_handle: ServerHandle):
        """Server should reject requests without auth header."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server_handle.port}/mcp", timeout=5.0)
            assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_auth_rejects_wrong_token(self, server_handle: ServerHandle):
        """Server should reject requests with wrong token."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://127.0.0.1:{server_handle.port}/mcp",
                headers={"Authorization": "Bearer wrong-token"},
                timeout=5.0,
            )
            assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_url_format(self, server_handle: ServerHandle):
        """URL should use host.docker.internal for Docker accessibility."""
        assert server_handle.url.startswith("http://host.docker.internal:")
        assert str(server_handle.port) in server_handle.url
