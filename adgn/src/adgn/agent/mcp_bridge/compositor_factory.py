"""Factory for creating the global user-facing compositor.

The global compositor aggregates:
- agents management server (list/create/delete/boot agents)
- per-agent compositors (mounted dynamically as agents are created)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from adgn.agent.mcp_bridge.agents import make_agents_server
from adgn.mcp.compositor.server import Compositor

if TYPE_CHECKING:
    from adgn.agent.mcp_bridge.registry import InfrastructureRegistry

logger = logging.getLogger(__name__)

# Server name for agents management
AGENTS_SERVER_NAME = "agents"


async def create_global_compositor(registry: InfrastructureRegistry) -> Compositor:
    """Create the global user-facing compositor.

    The global compositor provides:
    - agents://list resource - list all agents
    - agents://presets resource - list available presets
    - create_agent tool - create new agent from preset
    - delete_agent tool - delete an agent
    - boot_agent tool - boot existing agent from DB

    Per-agent compositors are mounted dynamically when agents are created/booted.
    Tools and resources from agent compositors are prefixed with agent_{id}/.

    Args:
        registry: InfrastructureRegistry for agent management

    Returns:
        Compositor with agents server mounted
    """
    # Create the global compositor
    compositor = Compositor("global", eager_open=True)

    # Create and mount agents management server
    agents_server = make_agents_server(AGENTS_SERVER_NAME, registry)
    await compositor.mount_inproc(AGENTS_SERVER_NAME, agents_server)
    logger.info("Mounted agents management server on global compositor")

    # Store reference in registry so agents can be mounted here
    registry.global_compositor = compositor

    return compositor
