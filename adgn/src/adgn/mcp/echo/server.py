from __future__ import annotations

from fastmcp.server import FastMCP


def build_echo_tools(s: FastMCP) -> None:
    @s.tool()
    def echo(text: str) -> dict[str, str]:  # noqa: D401 - simple echo tool
        return {"echo": text}


def make_echo_server(name: str = "echo") -> FastMCP:
    """In-proc FastMCP server that echoes its input as structured content.

    Exposes a single tool `echo(text: str)` returning structured content
    {"echo": text}.

    Used for tests and local development.
    """
    mcp = FastMCP(name)
    build_echo_tools(mcp)
    return mcp
