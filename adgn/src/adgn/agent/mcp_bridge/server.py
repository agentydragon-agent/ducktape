"""HTTP MCP Bridge Server - exposes Compositor over HTTP/SSE transport.

This is a standard MCP server (Compositor) exposed via HTTP transport.
External agents connect using MCP-over-HTTP and get policy-gated access to tools.
"""

from __future__ import annotations

import logging
from pathlib import Path

from docker import DockerClient
from fastmcp.mcp_config import MCPConfig

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import MCPInfrastructure
from adgn.agent.runtime.sidecars import SidecarBundle

logger = logging.getLogger(__name__)


async def create_bridge_infrastructure(
    agent_id: str,
    persistence: SQLitePersistence,
    docker_client: DockerClient,
    mcp_config: MCPConfig,
    initial_policy: str | None = None,
):
    """Create RunningInfrastructure for external agent HTTP bridge."""
    # Create infrastructure builder
    builder = MCPInfrastructure(
        agent_id=agent_id,
        persistence=persistence,
        docker_client=docker_client,
        initial_policy=initial_policy,
    )

    # Start core infrastructure
    running = await builder.start(mcp_config)

    # Attach sidecars (none for external agents)
    bundle = SidecarBundle.for_external_agent()
    await bundle.attach_all(running)

    return running


# Future enhancements (core functionality is complete):
# - Add authentication middleware for token → agent_id mapping
# - Handle multi-tenancy (multiple external agents with different agent_ids)
# - Add cleanup for idle infrastructure instances
