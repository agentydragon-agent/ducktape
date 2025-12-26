from __future__ import annotations

from fastmcp.server import FastMCP
from fastmcp.server.auth import AuthProvider

from adgn.mcp.http_gateway import mcp_http_gateway


class _DummyServer(FastMCP):
    def __init__(self, auth: AuthProvider):
        super().__init__("dummy", instructions="dummy", auth=auth)


async def test_http_gateway_starts_and_stops(async_docker_client):
    async with mcp_http_gateway(
        make_server=lambda auth: _DummyServer(auth), docker_client=async_docker_client, network_name="bridge"
    ) as gw:
        assert gw.url_for_container.startswith("http://")
        assert gw.token
        # ensure shutdown does not raise
    # after context exit, nothing to assert; just ensure no exceptions
