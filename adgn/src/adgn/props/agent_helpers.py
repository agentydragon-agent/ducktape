"""Helpers for agents running inside the runtime container.

Provides MCP HTTP client via mcp_client_from_env() for connecting to MCP servers.

Database access: Just use get_session() directly - it auto-initializes from PG* env vars.

Usage:

    # Database access (auto-initializes on first use)
    from adgn.props.db import get_session
    from adgn.props.db.models import Snapshot

    with get_session() as session:
        snapshots = session.query(Snapshot).filter_by(split='train').all()

    # MCP HTTP client
    from adgn.props.agent_helpers import mcp_client_from_env

    async with mcp_client_from_env() as (client, _):
        result = await client.call_tool("tool_name", {"arg": "value"})
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import os

from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import InitializeResult

logger = logging.getLogger(__name__)


@asynccontextmanager
async def mcp_client_from_env() -> AsyncGenerator[tuple[Client, InitializeResult], None]:
    """Create MCP client from environment variables.

    Reads MCP_SERVER_URL and MCP_SERVER_TOKEN from environment,
    creates authenticated HTTP client, and returns initialized client
    along with initialization result.

    This is used by agents running in containers that need to connect
    to MCP servers on the host via HTTP transport.

    Environment variables:
        MCP_SERVER_URL: Full HTTP endpoint URL (e.g., "http://172.19.0.1:12345/mcp")
        MCP_SERVER_TOKEN: Bearer token for authentication

    Yields:
        Tuple of (Client, InitializeResult):
        - client: Initialized fastmcp Client ready to call tools, read resources, etc.
        - init_result: Server info including capabilities, instructions, protocol version

    Raises:
        KeyError: If environment variables are not set
        Exception: If connection or initialization fails

    Example:
        async with mcp_client_from_env() as (client, init_result):
            # Print server instructions
            if init_result.instructions:
                print(init_result.instructions)

            # List available tools
            tools = await client.list_tools()
            for tool in tools:
                print(f"Tool: {tool.name}")

            # Call a tool
            result = await client.call_tool("tool_name", {"arg": "value"})
            # fastmcp client returns CallToolResult with is_error and structured_content

            # Read a resource
            contents = await client.read_resource("resource://server/name")
            for content in contents:
                print(content.text if hasattr(content, 'text') else content.blob)
    """
    url = os.environ["MCP_SERVER_URL"]
    token = os.environ["MCP_SERVER_TOKEN"]

    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        # Client auto-initializes on __aenter__, get the result
        init_result = client.initialize_result
        if init_result is None:
            raise RuntimeError("Client did not initialize properly")
        yield client, init_result
