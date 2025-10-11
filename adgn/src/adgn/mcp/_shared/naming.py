from __future__ import annotations

"""Canonical MCP tool naming helpers.

Single source of truth for building and parsing namespaced MCP tool names.

Format: "mcp__{server}__{tool}". A bare "{server}__{tool}" is also accepted
by the parser for compatibility.
"""

MCP_NAMESPACE_PREFIX = "mcp__"


def build_mcp_function(server: str, tool: str) -> str:
    return f"{MCP_NAMESPACE_PREFIX}{server}__{tool}"


def parse_mcp_function(namespaced: str) -> tuple[str, str]:
    if namespaced.startswith(MCP_NAMESPACE_PREFIX):
        remainder = namespaced[len(MCP_NAMESPACE_PREFIX) :]
    else:
        remainder = namespaced
    if "__" not in remainder:
        raise ValueError(f"Invalid MCP tool name: {namespaced}")
    server, tool = remainder.split("__", 1)
    if not server or not tool:
        raise ValueError(f"Invalid MCP tool name: {namespaced}")
    return server, tool


# Internal helpers; avoid barrels
