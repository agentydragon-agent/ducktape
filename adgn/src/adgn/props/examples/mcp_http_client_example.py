"""Example: Connect to MCP server via Streamable HTTP transport.

This demonstrates how to connect to an MCP server using HTTP transport with
bearer token authentication. The server URL and token are provided via
environment variables.

Usage:
    python mcp_http_client_example.py

Environment variables:
    MCP_SERVER_URL: Full HTTP endpoint URL (e.g., http://172.19.0.1:12345/mcp)
    MCP_SERVER_TOKEN: Bearer token for authentication
"""

from __future__ import annotations

import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main() -> None:
    """Connect to MCP server and inspect available tools."""
    # Get connection details from environment
    server_url = os.getenv("MCP_SERVER_URL")
    server_token = os.getenv("MCP_SERVER_TOKEN")

    if not server_url or not server_token:
        raise RuntimeError("MCP_SERVER_URL and MCP_SERVER_TOKEN must be set")

    # Connect to MCP server via HTTP
    async with streamablehttp_client(
        server_url, headers={"Authorization": f"Bearer {server_token}"}
    ) as (read, write, _), ClientSession(read, write) as session:
        # 1. Initialize - get server info and instructions
        init_result = await session.initialize()
        print("Server instructions:")
        print(init_result.instructions)
        print()

        # 2. List available tools - inspect their schemas
        tools_result = await session.list_tools()
        print(f"Available tools: {len(tools_result.tools)}")
        for tool in tools_result.tools:
            print(f"\nTool: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Input Schema: {tool.inputSchema}")

        # 3. Call tools as needed
        # Example: result = await session.call_tool("tool_name", arguments={...})


if __name__ == "__main__":
    asyncio.run(main())
