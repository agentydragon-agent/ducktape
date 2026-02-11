"""Stdio MCP server for testing notifications."""

from __future__ import annotations

import anyio

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

m = NotifyingFastMCP("stdio_child")


@m.tool(name="emit")
async def emit():  # type: ignore[empty-body]
    """Emit test notifications."""
    await m.broadcast_resource_list_changed()
    await m.broadcast_resource_updated("resource://dummy")
    return True


def main() -> None:
    """Run the notifying MCP server over stdio."""
    anyio.run(m.run_stdio_async)


if __name__ == "__main__":
    main()
