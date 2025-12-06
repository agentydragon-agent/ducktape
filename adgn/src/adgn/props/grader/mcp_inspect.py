"""Example MCP HTTP client for one-off operations.

This script demonstrates the typical pattern for interacting with an MCP server
over HTTP in a one-off script. The session lifecycle is:
1. Connect to the server using streamablehttp_client
2. Initialize the session (REQUIRED before using tools/resources)
3. Use tools, list resources, etc.
4. Session is automatically closed when the script exits

For submitting results, follow this same pattern: connect, initialize, call the
submit_result tool, then let the session close naturally at script exit.
"""

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = os.getenv("MCP_SERVER_URL")
    token = os.getenv("MCP_SERVER_TOKEN")

    if not url:
        print("ERROR: MCP_SERVER_URL environment variable is not set", file=sys.stderr)
        print("Ensure ADGN_USE_MCP_HTTP=1 is set when running the grader", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("ERROR: MCP_SERVER_TOKEN environment variable is not set", file=sys.stderr)
        sys.exit(1)

    # Connect to the MCP server via Streamable HTTP transport
    async with (
        streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        # REQUIRED: Initialize session before using tools/resources
        init = await session.initialize()
        print(init.serverInfo, init.instructions)

        # Now we can list tools and resources
        print("=== Tools ===")
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            print(tool.name, tool.description, tool.inputSchema)

        print("=== Resources ===")
        resources_result = await session.list_resources()
        for res in resources_result.resources:
            print(res.uri, res.name, res.description)

        # Example: How to call a tool and read its results
        print("\n=== Example Tool Call ===")

        # Call a tool with arguments
        result = await session.call_tool(
            "example_tool", arguments={"param1": "value1", "param2": 42, "nested": {"key": "value"}}
        )

        # Check if the call succeeded or failed
        if result.isError:
            print(f"Tool call failed: {result.content}")
            sys.exit(1)
        else:
            print("Tool call succeeded!")
            print(f"Result content: {result.content}")
            # result.content contains the tool's return value

        # Session will be closed automatically when exiting the context manager


if __name__ == "__main__":
    asyncio.run(main())
