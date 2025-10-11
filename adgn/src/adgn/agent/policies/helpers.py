from __future__ import annotations

# Use canonical approval engine types (no renaming)
from adgn.mcp._shared.naming import parse_mcp_function


def split_tool_name(name: str) -> tuple[str, str]:
    """Split a fully-qualified tool name to (server, tool).

    Accepts the canonical namespaced MCP form ("mcp__{server}__{tool}") and
    the bare fallback ("{server}__{tool}"). Use this helper in policies instead
    of hand-rolled parsing.
    """
    return parse_mcp_function(name)


# Internal module; keep imports explicit at call sites (no barrels)
