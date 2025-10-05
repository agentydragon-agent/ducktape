from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


def make_echo_mcp(name: str = "echo") -> FastMCP:
    """In-proc FastMCP server that echoes its input as structured content.

    Exposes a single tool `echo(text: str) -> dict[str, Any]` returning
    {"ok": True, "echo": text}.

    Used for tests and local development.
    """
    mcp = FastMCP(name)

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:  # noqa: D401 - simple echo tool
        return {"ok": True, "echo": text}

    return mcp
