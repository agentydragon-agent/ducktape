"""Infrastructure registry for Phase 5 two-compositor architecture.

Manages:
- Global user-facing compositor
- Per-agent containers (internal and external)
- Agent lifecycle (create, boot, shutdown)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging

from docker.client import DockerClient
from fastmcp.mcp_config import MCPConfig

from adgn.agent.mcp_bridge.servers.agent_control import make_agent_control_server
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.presets import create_agent_from_preset
from adgn.agent.runtime.container import AgentContainer, build_container
from adgn.agent.types import AgentID
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.model import OpenAIModelProto

# Server name for agent control (send_prompt, abort_run)
AGENT_CONTROL_SERVER_NAME = "agent_control"

logger = logging.getLogger(__name__)


@dataclass
class InfrastructureRegistry:
    """Registry managing global compositor and agent containers.

    The registry owns:
    - Global user-facing compositor (all agents visible to user)
    - Per-agent containers (user + agent compositors)
    - Agent lifecycle operations

    Token routing is handled by TokenRoutingASGI at the ASGI level.
    """

    persistence: SQLitePersistence
    model: str
    client_factory: Callable[[str], OpenAIModelProto]
    docker_client: DockerClient
    mcp_config: MCPConfig  # Base MCP config for new agents
    initial_policy: str | None = None

    # Global user-facing compositor (set by app.py after creation)
    global_compositor: Compositor | None = None

    # Agent containers keyed by agent_id
    _agents: dict[AgentID, AgentContainer] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Track which agents are external (cannot be controlled via UI)
    _external_agents: set[AgentID] = field(default_factory=set)

    def get_agent(self, agent_id: AgentID) -> AgentContainer | None:
        """Get agent container by ID."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentContainer]:
        """List all agent containers."""
        return list(self._agents.values())

    def is_external(self, agent_id: AgentID) -> bool:
        """Check if agent is external (cannot be controlled via UI)."""
        return agent_id in self._external_agents

    async def _mount_agent_control(self, container: AgentContainer) -> None:
        """Mount agent_control server on container's compositor.

        Only for internal agents - provides send_prompt and abort_run tools.
        """
        if container._compositor is None:
            logger.warning(f"Cannot mount agent_control: compositor not initialized for {container.agent_id}")
            return

        control_server = make_agent_control_server(AGENT_CONTROL_SERVER_NAME, container)
        await container._compositor.mount_inproc(AGENT_CONTROL_SERVER_NAME, control_server)
        logger.debug(f"Mounted agent_control for internal agent: {container.agent_id}")

    async def _create_container(
        self,
        agent_id: AgentID,
        *,
        mcp_config: MCPConfig | None = None,
        system: str | None = None,
        external: bool = False,
    ) -> AgentContainer:
        """Internal: create a new agent container.

        Args:
            agent_id: Agent identifier
            mcp_config: MCP config (uses default if not provided)
            system: System prompt override
            external: Whether this is an external agent (no agent_control)

        Returns:
            Created AgentContainer (not yet started)
        """
        config = mcp_config or self.mcp_config
        container = await build_container(
            agent_id=agent_id,
            mcp_config=config,
            persistence=self.persistence,
            model=self.model,
            client_factory=self.client_factory,
            with_ui=True,
            system=system,
            docker_client=self.docker_client,
            initial_policy=self.initial_policy,
        )
        if external:
            self._external_agents.add(agent_id)
        return container

    async def create_agent(self, preset: str | None = None) -> AgentContainer:
        """Create a NEW agent from preset and boot it immediately.

        This is for internal agents only. Creates agent record in DB,
        boots the container, and mounts user compositor to global.

        Args:
            preset: Preset name to use for agent configuration

        Returns:
            Booted AgentContainer

        Raises:
            RuntimeError: If global compositor is not set
        """
        if self.global_compositor is None:
            raise RuntimeError("Cannot create agent: global compositor not initialized")

        async with self._lock:
            # Create agent record in DB from preset
            agent_id, mcp_config, system = await create_agent_from_preset(
                persistence=self.persistence, preset_name=preset, base_mcp_config=self.mcp_config
            )

            # Build and start container
            container = await self._create_container(agent_id, mcp_config=mcp_config, system=system, external=False)
            self._agents[agent_id] = container

            # Mount agent_control for internal agents
            await self._mount_agent_control(container)

            # Mount agent compositor to global
            await self.global_compositor.mount_inproc(f"agent_{agent_id}", container._compositor)

            return container

    async def boot_agent(self, agent_id: AgentID) -> AgentContainer:
        """Boot an EXISTING agent that has state in DB.

        Used for internal agents only. Loads agent from persistence,
        boots the container, and mounts user compositor to global.

        Args:
            agent_id: Agent identifier (must exist in DB)

        Returns:
            Booted AgentContainer

        Raises:
            RuntimeError: If global compositor is not set
            KeyError: If agent doesn't exist in DB
        """
        if self.global_compositor is None:
            raise RuntimeError("Cannot boot agent: global compositor not initialized")

        async with self._lock:
            # Return existing if already booted
            if agent_id in self._agents:
                return self._agents[agent_id]

            # Load from persistence
            row = await self.persistence.get_agent(agent_id)
            if row is None:
                raise KeyError(f"Agent not found: {agent_id}")

            # Build and start container
            container = await self._create_container(agent_id, mcp_config=row.mcp_config, external=False)
            self._agents[agent_id] = container

            # Mount agent_control for internal agents
            await self._mount_agent_control(container)

            # Mount agent compositor to global
            await self.global_compositor.mount_inproc(f"agent_{agent_id}", container._compositor)

            return container

    async def create_external_agent(self, agent_id: AgentID) -> AgentContainer:
        """Create an external agent's container at startup.

        External agents are created eagerly from tokens config.
        Like boot_agent(), this ALSO mounts user compositor to global
        so the user sees all agents (internal + external) in the same UI.

        External agents have limitations:
        - No agent_control server (can't send_prompt, can't abort)
        - User can only view state and approve/reject

        Args:
            agent_id: Agent identifier

        Returns:
            Created AgentContainer

        Raises:
            RuntimeError: If global compositor is not set
        """
        if self.global_compositor is None:
            raise RuntimeError("Cannot create external agent: global compositor not initialized")

        async with self._lock:
            if agent_id in self._agents:
                return self._agents[agent_id]

            # Check if agent exists in DB, create if not
            row = await self.persistence.get_agent(agent_id)
            mcp_config = row.mcp_config if row else self.mcp_config

            container = await self._create_container(agent_id, mcp_config=mcp_config, external=True)
            self._agents[agent_id] = container

            # NOTE: No agent_control mount for external agents
            # User can view state and approve/reject, but cannot send_prompt or abort_run

            # Mount agent compositor to global
            await self.global_compositor.mount_inproc(f"agent_{agent_id}", container._compositor)

            logger.info(f"Created external agent: {agent_id}")
            return container

    async def shutdown_agent(self, agent_id: AgentID) -> None:
        """Shutdown agent and unmount its user compositor.

        Raises:
            RuntimeError: If global compositor is not set
            KeyError: If agent is not running
        """
        if self.global_compositor is None:
            raise RuntimeError("Cannot shutdown agent: global compositor not initialized")

        async with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Agent not running: {agent_id}")

            # Unmount from global
            try:
                await self.global_compositor.unmount_server(f"agent_{agent_id}")
            except Exception as e:
                logger.warning(f"Failed to unmount agent {agent_id}: {e}")

            # Close container
            container = self._agents.pop(agent_id)
            await container.close()

            # Clean up external tracking
            self._external_agents.discard(agent_id)

            logger.info(f"Shutdown agent: {agent_id}")

    async def shutdown_all(self) -> None:
        """Shutdown all agents.

        Raises:
            RuntimeError: If global compositor is not set and agents exist
        """
        if not self._agents:
            return
        if self.global_compositor is None:
            raise RuntimeError("Cannot shutdown agents: global compositor not initialized")

        agent_ids = list(self._agents.keys())
        for agent_id in agent_ids:
            # shutdown_agent checks are satisfied by the guard above
            await self.shutdown_agent(agent_id)
