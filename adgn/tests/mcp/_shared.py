"""Shared test helpers/constants for MCP tests.

Keeps server names and MCP tool name construction DRY across tests.
"""

from __future__ import annotations

from adgn.agent.mcp_manager import build_mcp_function


def mcp_name(server: str, tool: str) -> str:
    """Build a namespaced MCP function name for server/tool.

    Wrapper around the central helper to avoid hardcoding the "mcp__" prefix.
    """
    return build_mcp_function(server, tool)
