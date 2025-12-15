"""Helpers for agents running inside the runtime container.

This module provides simple access to:
- Database ORM and query interface
- Environment configuration from container environment
- MCP HTTP client for connecting to networked MCP servers

Usage from within an agent (e.g., prompt optimizer):

    # Database access
    from adgn.props.agent_helpers import setup_agent_database
    from adgn.props.db import get_session
    from adgn.props.db.models import Snapshot, GraderRun

    setup_agent_database()  # One-time setup (reads env, initializes connection)

    with get_session() as session:
        snapshots = session.query(Snapshot).filter_by(split='train').all()

    # MCP HTTP client access
    from adgn.props.agent_helpers import mcp_client_from_env

    async with mcp_client_from_env() as session:
        result = await session.call_tool("tool_name", {"arg": "value"})
        resource = await session.read_resource("resource://server/name")
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from adgn.props.db.config import DatabaseConfig, get_database_config
from adgn.props.db.session import init_db

logger = logging.getLogger(__name__)


def get_agent_database_config() -> DatabaseConfig:
    """Get database configuration for agent running in container.

    Reads from standard PostgreSQL environment variables that are passed from host to container.
    For agents inside containers, PROPS_DB_* vars are NOT set (container_name/container_port will be None).

    Returns:
        DatabaseConfig with agent credentials and no container routing

    Raises:
        ValueError: If required PG* environment variables not set
    """
    # Use unified factory - agents have PROPS_DB_* vars unset, so container_name/port will be None
    return get_database_config()


def setup_agent_database() -> None:
    """Initialize database connection for agent with read-only access.

    Call once at agent startup to set up the connection pool.
    After calling this, use get_session() to query the database.

    Raises:
        ValueError: If required environment variables not set
        sqlalchemy.exc.OperationalError: If cannot connect to database
    """
    config = get_agent_database_config()
    logger.info(
        f"Initializing agent database connection: {config.admin.host}:{config.admin.port}/{config.admin.database} "
        f"(user: {config.admin.user})"
    )
    init_db(config)
    logger.info("Agent database connection initialized (read-only access)")


@asynccontextmanager
async def mcp_client_from_env() -> AsyncGenerator[tuple[ClientSession, object], None]:
    """Create MCP client session from environment variables.

    Reads MCP_SERVER_URL and MCP_SERVER_TOKEN from environment,
    creates authenticated HTTP client, and returns initialized session
    along with initialization result.

    This is used by agents running in containers that need to connect
    to MCP servers on the host via HTTP transport.

    Environment variables:
        MCP_SERVER_URL: Full HTTP endpoint URL (e.g., "http://172.19.0.1:12345/mcp")
        MCP_SERVER_TOKEN: Bearer token for authentication

    Yields:
        Tuple of (ClientSession, InitializeResult):
        - session: Initialized client ready to call tools, read resources, etc.
        - init_result: Server info including capabilities, instructions, protocol version

    Raises:
        KeyError: If environment variables are not set
        Exception: If connection or initialization fails

    Example:
        async with mcp_client_from_env() as (session, init_result):
            # Print server instructions
            if init_result.instructions:
                print(init_result.instructions)

            # List available tools
            tools = await session.list_tools()

            # Call a tool
            result = await session.call_tool("tool_name", {"arg": "value"})

            # Read a resource
            resource = await session.read_resource("resource://server/name")
    """
    url = os.environ["MCP_SERVER_URL"]
    token = os.environ["MCP_SERVER_TOKEN"]

    async with (
        streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        # Initialize session to get server info
        init_result = await session.initialize()
        yield session, init_result
