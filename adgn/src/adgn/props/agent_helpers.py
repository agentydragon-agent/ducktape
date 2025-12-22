"""Helpers for agents running inside the runtime container.

Provides:
- get_current_agent_run_id(): Get agent run ID from PostgreSQL RLS context
- mcp_client_from_env(): Create MCP HTTP client from environment variables

Database access: Just use get_session() directly - it auto-initializes from PG* env vars.

Usage:

    # Get agent run ID (from database - extracts from username pattern)
    from adgn.props.db import get_session
    from adgn.props.agent_helpers import get_current_agent_run_id

    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)

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
from typing import TYPE_CHECKING
from uuid import UUID

from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import InitializeResult
from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from adgn.props.db.models import AgentRun

logger = logging.getLogger(__name__)


def get_current_agent_run_id(session: Session) -> UUID:
    """Get the current agent run ID from the database.

    Uses the PostgreSQL current_agent_run_id() function which extracts
    the UUID from the database username (e.g., agent_{uuid} pattern).

    This is the canonical way to get the current agent's run ID when running
    inside the container. The database extracts the ID from the agent user's
    username pattern.

    Args:
        session: Active SQLAlchemy session

    Returns:
        UUID of the current agent run

    Raises:
        RuntimeError: If not connected as an agent user, or if the
                      current_agent_run_id() function returns NULL
    """
    result = session.execute(text("SELECT current_agent_run_id()"))
    agent_run_id = result.scalar()
    if agent_run_id is None:
        raise RuntimeError(
            "current_agent_run_id() returned NULL - not connected as an agent user. "
            "Make sure you're using agent credentials (e.g., critic_agent_{uuid})."
        )
    if not isinstance(agent_run_id, UUID):
        agent_run_id = UUID(str(agent_run_id))
    return agent_run_id


def get_current_agent_run(session: Session) -> AgentRun:
    """Get the current agent run ORM object from the database.

    Combines get_current_agent_run_id() with loading the AgentRun record.
    Use this when you need the full AgentRun object with typed access to
    type_config via methods like prompt_optimizer_config().

    Args:
        session: Active SQLAlchemy session

    Returns:
        AgentRun object for the current agent

    Raises:
        RuntimeError: If not connected as an agent user
        ValueError: If agent run record not found in database

    Example:
        with get_session() as session:
            run = get_current_agent_run(session)
            config = run.prompt_optimizer_config()  # Type-safe access
            print(f"Target metric: {config.target_metric}")
    """
    # Import here to avoid circular dependency
    from adgn.props.db.models import AgentRun

    agent_run_id = get_current_agent_run_id(session)
    agent_run = session.get(AgentRun, agent_run_id)
    if agent_run is None:
        raise ValueError(f"AgentRun not found for agent_run_id={agent_run_id}")
    return agent_run


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
