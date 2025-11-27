"""Agents management MCP server.

Provides tools and resources for managing agents:
- list resource: all agents with state
- presets resource: available presets
- create_agent tool: create new agent from preset
- delete_agent tool: delete an agent
- boot_agent tool: boot existing agent from DB
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from adgn.agent.presets import discover_presets
from adgn.mcp._shared.fastmcp_flat import FlatModelFastMCP

if TYPE_CHECKING:
    from adgn.agent.mcp_bridge.registry import InfrastructureRegistry

logger = logging.getLogger(__name__)


# ---- Resource models ---------------------------------------------------------


class AgentInfo(BaseModel):
    """Agent information for list resource."""

    id: str
    preset: str | None = None
    external: bool = False
    booted: bool = False


class PresetInfo(BaseModel):
    """Preset information for presets resource."""

    name: str
    description: str | None = None


# ---- Tool I/O models ---------------------------------------------------------


class CreateAgentInput(BaseModel):
    """Input for create_agent tool."""

    preset: str | None = Field(default=None, description="Preset name to use (default: 'default')")


class CreateAgentOutput(BaseModel):
    """Output for create_agent tool."""

    id: str
    status: Literal["created"]
    preset: str


class DeleteAgentInput(BaseModel):
    """Input for delete_agent tool."""

    agent_id: str = Field(description="Agent ID to delete")


class DeleteAgentOutput(BaseModel):
    """Output for delete_agent tool."""

    id: str
    status: Literal["deleted"]


class BootAgentInput(BaseModel):
    """Input for boot_agent tool."""

    agent_id: str = Field(description="Agent ID to boot (must exist in DB)")


class BootAgentOutput(BaseModel):
    """Output for boot_agent tool."""

    id: str
    status: Literal["booted"]


# ---- Server factory ----------------------------------------------------------


def make_agents_server(name: str, registry: InfrastructureRegistry) -> FlatModelFastMCP:
    """Create the agents management MCP server.

    Resources:
    - agents://list - List all agents with state
    - agents://presets - List available presets

    Tools:
    - create_agent(preset) - Create new agent from preset
    - delete_agent(agent_id) - Delete an agent
    - boot_agent(agent_id) - Boot existing agent from DB
    """
    mcp = FlatModelFastMCP(name)

    @mcp.resource("agents://list")
    async def list_agents() -> list[AgentInfo]:
        """List all agents with their state.

        Returns agents from both:
        - Running containers in registry
        - Persisted agents in DB (not yet booted)
        """
        agents: list[AgentInfo] = []

        # Get running agents from registry
        for container in registry.list_agents():
            agent_id = container.agent_id
            # Get preset from persistence
            row = await registry.persistence.get_agent(agent_id)
            preset = row.metadata.preset if (row and row.metadata) else None
            agents.append(AgentInfo(id=agent_id, preset=preset, external=registry.is_external(agent_id), booted=True))

        # Get persisted agents that aren't running
        running_ids = {c.agent_id for c in registry.list_agents()}
        persisted = await registry.persistence.list_agents()
        for row in persisted:
            if row.id not in running_ids:
                preset = row.metadata.preset if row.metadata else None
                agents.append(AgentInfo(id=row.id, preset=preset, external=False, booted=False))

        return agents

    @mcp.resource("agents://presets")
    async def list_presets() -> list[PresetInfo]:
        """List available agent presets."""
        presets = discover_presets()
        return [PresetInfo(name=p.name, description=p.description) for p in presets.values()]

    @mcp.tool(flat=True)
    async def create_agent(input: CreateAgentInput) -> CreateAgentOutput:
        """Create a new agent from a preset and boot it."""
        container = await registry.create_agent(preset=input.preset)
        await mcp.notify_resource_updated("agents://list")
        return CreateAgentOutput(id=container.agent_id, status="created", preset=input.preset or "default")

    @mcp.tool(flat=True)
    async def delete_agent(input: DeleteAgentInput) -> DeleteAgentOutput:
        """Delete an agent."""
        await registry.shutdown_agent(input.agent_id)
        await registry.persistence.delete_agent(input.agent_id)
        await mcp.notify_resource_updated("agents://list")
        return DeleteAgentOutput(id=input.agent_id, status="deleted")

    @mcp.tool(flat=True)
    async def boot_agent(input: BootAgentInput) -> BootAgentOutput:
        """Boot an existing agent from the database."""
        container = await registry.boot_agent(input.agent_id)
        await mcp.notify_resource_updated("agents://list")
        return BootAgentOutput(id=container.agent_id, status="booted")

    return mcp
