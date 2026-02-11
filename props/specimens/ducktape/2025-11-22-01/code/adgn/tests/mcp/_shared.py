"""Shared test helpers/constants for MCP tests.

Keeps server names and MCP tool name construction DRY across tests.
"""

from __future__ import annotations

from adgn.mcp._shared.naming import build_mcp_function


def mcp_name(server: str, tool: str) -> str:
    """Build a namespaced MCP function name for server/tool.

    Raises ValueError if the components contain double underscores to mirror the
    constraints enforced throughout the agent codebase.
    """
    if not server or "__" in server:
        raise ValueError(f"invalid MCP server name: {server!r}")
    if not tool or "__" in tool:
        raise ValueError(f"invalid MCP tool name: {tool!r}")
    return build_mcp_function(server, tool)
