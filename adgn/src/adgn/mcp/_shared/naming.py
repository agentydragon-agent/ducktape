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


def parse_tool_name(name: str) -> tuple[str, str]:
    """Parse a tool name into (server, tool) tuple.

    Inverse of build_mcp_function(). Expects format: {server}_{tool}.
    Tool portion may contain underscores.

    Raises:
        ValueError: If name doesn't contain exactly one underscore separator,
                   or if either server or tool portion is empty.
    """

    def _err(detail: str) -> str:
        return f"Invalid tool name format: {name!r}. {detail}"

    parts = name.split("_", 1)
    if len(parts) != 2:
        raise ValueError(_err("Expected 'server_tool'."))
    server, tool = parts[0], parts[1]
    if not server:
        raise ValueError(_err("Server portion is empty."))
    if not tool:
        raise ValueError(_err("Tool portion is empty."))
    return (server, tool)


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
