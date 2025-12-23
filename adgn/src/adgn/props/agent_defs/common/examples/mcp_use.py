"""Example: Connect to MCP server via Streamable HTTP transport with Bearer token."""

from __future__ import annotations

import asyncio
import os

from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main() -> None:
    server_url = os.getenv("MCP_SERVER_URL")
    server_token = os.getenv("MCP_SERVER_TOKEN")

    if not server_url or not server_token:
        raise RuntimeError("MCP_SERVER_URL and MCP_SERVER_TOKEN must be set")

    # Connect to MCP server via HTTP using fastmcp
    transport = StreamableHttpTransport(
        server_url, headers={"Authorization": f"Bearer {server_token}"}
    )
    async with Client(transport) as client:
        # 1. Get initialization result with server info and instructions
        init_result = client.initialize_result
        print("Server instructions:")
        print(init_result.instructions)

        # 2. List available tools - inspect their schemas
        tools = await client.list_tools()
        for tool in tools:
            print(tool.name)
            print(tool.description)
            print(tool.inputSchema)

        # 3. Call tools as needed
        # result = await client.call_tool("tool_name", arguments={...})


if __name__ == "__main__":
    asyncio.run(main())
