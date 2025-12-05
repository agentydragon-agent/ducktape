"""Tests for the ephemeral MCP HTTP server launcher.

Tests lifecycle management, port allocation, and basic connectivity.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adgn.props.servers.http_launcher import ServerHandle, launch_mcp_http_server


def _create_test_server(token: str):
    """Create a minimal FastMCP server for testing."""
    from fastmcp import FastMCP
    from fastmcp.server.auth import StaticTokenVerifier

    auth = StaticTokenVerifier(tokens={token: {"client_id": "test", "scopes": []}})
    server = FastMCP("test_server", auth=auth, instructions="Test server for HTTP launcher tests.")

    @server.tool()
    def echo(message: str) -> str:
        """Echo back the message."""
        return f"echo: {message}"

    return server


class TestLaunchMcpHttpServer:
    """Tests for launch_mcp_http_server context manager."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        """Server should start, be reachable, and stop cleanly."""
        async with launch_mcp_http_server(_create_test_server) as handle:
            assert isinstance(handle, ServerHandle)
            assert handle.port > 0
            assert handle.token  # Non-empty token
            assert "host.docker.internal" in handle.url

            # Server should be reachable
            async with httpx.AsyncClient() as client:
                # Health check via OPTIONS or GET on MCP endpoint
                response = await client.get(
                    f"http://127.0.0.1:{handle.port}/",
                    headers={"Authorization": f"Bearer {handle.token}"},
                    timeout=5.0,
                )
                # MCP servers may return various status codes, but should respond
                assert response.status_code in (200, 404, 405)

        # After context exit, server should be stopped
        # Give it a moment to fully shut down
        await asyncio.sleep(0.2)
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(f"http://127.0.0.1:{handle.port}/", timeout=1.0)

    @pytest.mark.asyncio
    async def test_auth_required(self):
        """Server should reject requests without valid token."""
        async with launch_mcp_http_server(_create_test_server) as handle:
            async with httpx.AsyncClient() as client:
                # Request without auth header
                response = await client.get(
                    f"http://127.0.0.1:{handle.port}/mcp",
                    timeout=5.0,
                )
                # Should be unauthorized
                assert response.status_code in (401, 403)

                # Request with wrong token
                response = await client.get(
                    f"http://127.0.0.1:{handle.port}/mcp",
                    headers={"Authorization": "Bearer wrong-token"},
                    timeout=5.0,
                )
                assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_url_format(self):
        """URL should use host.docker.internal for Docker accessibility."""
        async with launch_mcp_http_server(_create_test_server) as handle:
            assert handle.url.startswith("http://host.docker.internal:")
            assert str(handle.port) in handle.url
