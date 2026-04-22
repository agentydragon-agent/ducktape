"""FastMCP proxy wiring for the Tana OAuth facade."""

from __future__ import annotations

from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import ProxyClient

from tana.mcp_facade.config import ServerSettings


def build_proxy_server(settings: ServerSettings, **kwargs: object):
    """Create a FastMCP proxy to the downstream Tana MCP server."""
    transport = StreamableHttpTransport(settings.downstream_url, auth=settings.static_bearer_token)
    return create_proxy(
        ProxyClient(transport),
        name="Tana MCP Facade",
        instructions=(
            "OAuth-facing MCP facade for Tana. Authorization is enforced by the "
            "upstream Authentik application policy. Downstream requests use a "
            "server-held bearer token."
        ),
        **kwargs,
    )
