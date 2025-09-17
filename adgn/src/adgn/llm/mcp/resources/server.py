import json
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP


class ResourcesBackend(Protocol):
    """Backend expected by the resources FastMCP server.

    This server delegates to the backend's canonical, typed helpers that return
    JSON strings produced from Pydantic models (single source of truth lives in
    McpManager). We avoid any local windowing or ad-hoc dict assembly here.
    """

    async def resources_list_json(
        self,
        server_filter: str | None,
        uri_prefix: str | None,
    ) -> str: ...
    async def resources_read_json(
        self,
        server: str,
        uri: str,
        start_offset: int,
        max_bytes: int | None,
    ) -> str: ...


def make_resources_server(
    backend: ResourcesBackend,
    name: str = "resources",
) -> FastMCP:
    """Create a lightweight MCP server that aggregates resources across servers.

    Exposes two tools delegating to backend's canonical JSON helpers:
      - list(server?: string, uri_prefix?: string) -> { resources: [...] }
      - read(server: string, uri: string, start_offset?: int = 0, max_bytes?: int) -> windowed payload

    Backend is supplied directly as an argument (e.g., McpManager).
    """
    mcp = FastMCP(
        name,
        instructions="Aggregates MCP resources and provides read with windowing",
    )

    @mcp.tool()
    async def list(
        server: str | None = None,
        uri_prefix: str | None = None,
    ) -> dict[str, Any]:
        payload = await backend.resources_list_json(server, uri_prefix)
        return json.loads(payload)

    @mcp.tool()
    async def read(
        server: str,
        uri: str,
        start_offset: int = 0,
        max_bytes: int = 0,
    ) -> dict[str, Any]:
        # Preserve historical semantics: max_bytes <= 0 means "no limit"
        payload = await backend.resources_read_json(
            server=server,
            uri=uri,
            start_offset=start_offset,
            max_bytes=None if max_bytes <= 0 else max_bytes,
        )
        return json.loads(payload)

    return mcp
