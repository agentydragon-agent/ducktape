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

from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main() -> None:
    """Connect to MCP server and inspect available tools."""
    # Get connection details from environment
    server_url = os.getenv("MCP_SERVER_URL")
    server_token = os.getenv("MCP_SERVER_TOKEN")

    if not server_url or not server_token:
        raise RuntimeError("MCP_SERVER_URL and MCP_SERVER_TOKEN must be set")

    # Connect to MCP server via HTTP using fastmcp
    transport = StreamableHttpTransport(server_url, headers={"Authorization": f"Bearer {server_token}"})
    async with Client(transport) as client:
        # 1. Get initialization result - contains server info and instructions
        init_result = client.initialize_result
        print("Server instructions:")
        print(init_result.instructions if init_result else "N/A")
        print()

        # 2. List available tools - inspect their schemas
        tools = await client.list_tools()
        print(f"Available tools: {len(tools)}")
        for tool in tools:
            print(f"\nTool: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Input Schema: {tool.inputSchema}")

        # 3. Call tools as needed
        # Example: result = await client.call_tool("tool_name", arguments={...})


if __name__ == "__main__":
    asyncio.run(main())
