from __future__ import annotations

"""Canonical MCP tool naming helpers.

Single source of truth for building and parsing namespaced MCP tool names.

Format: ``{server}_{tool}``. A single underscore separates the server identifier
and tool name; the tool portion may itself contain underscores.
"""


def build_mcp_function(server: str, tool: str) -> str:
    """Return the fully-qualified tool name for the aggregated compositor surface."""
    if not server:
        raise ValueError(f"Invalid MCP server name: {server!r}")
    if not tool:
        raise ValueError("Tool name must be non-empty")
    return f"{server}_{tool}"


def tool_prefix(server: str) -> str:
    """Return the namespaced prefix for all tools exposed by ``server``."""
    if not server:
        raise ValueError("Server name must be non-empty")
    return f"{server}_"


def tool_matches(name: str, *, server: str, tool: str) -> bool:
    """Return True when ``name`` refers to the specified server/tool."""
    return name == build_mcp_function(server, tool)


def server_matches(name: str, *, server: str) -> bool:
    """Return True when ``name`` belongs to the specified server."""
    return name.startswith(tool_prefix(server))


def resource_prefix(server: str) -> str:
    """Return the namespaced prefix (without trailing underscore) for resources."""
    if not server:
        raise ValueError("Server name must be non-empty")
    return server


# Internal helpers; avoid barrels
