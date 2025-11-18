from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from docker import DockerClient
from fastmcp.mcp_config import MCPConfig

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.local_runtime import LocalAgentRuntime
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.openai_utils.model import OpenAIModelProto

from .builder import build_local_agent


@dataclass
class AgentRuntime:
    """Container for running agent (infrastructure + runtime).

    This replaces the old AgentContainer with the new architecture:
    - RunningInfrastructure (core MCP + policy gateway)
    - LocalAgentRuntime (MiniCodex agent)
    """

    agent_id: str
    running: RunningInfrastructure
    runtime: LocalAgentRuntime

    async def close(self) -> None:
        """Close agent runtime and infrastructure."""
        await self.runtime.close()
        await self.running.close()


@dataclass
class AgentRegistry:
    """Registry for managing agent runtimes (new architecture).

    This uses the new MCPInfrastructure + LocalAgentRuntime architecture
    instead of the old monolithic AgentContainer.
    """

    persistence: SQLitePersistence
    model: str
    client_factory: Callable[[str], OpenAIModelProto]
    docker_client: DockerClient
    _items: dict[str, AgentRuntime] = field(default_factory=dict)

    def get(self, agent_id: str) -> AgentRuntime | None:
        return self._items.get(agent_id)

    def list(self) -> list[AgentRuntime]:
        return list(self._items.values())

    async def create(
        self,
        agent_id: str,
        mcp_config: MCPConfig,
        *,
        with_ui: bool = True,
        ui_bus=None,
        connection_manager=None,
        system: str | None = None,
    ) -> AgentRuntime:
        """Create and start a new agent runtime.

        Args:
            agent_id: Agent identifier
            mcp_config: MCP servers to mount
            with_ui: Whether to attach UI sidecar
            ui_bus: ServerBus for UI (required if with_ui=True)
            connection_manager: Connection manager for UI notifications
            system: Optional system prompt override
        """
        running, runtime = await build_local_agent(
            agent_id=agent_id,
            mcp_config=mcp_config,
            persistence=self.persistence,
            model=self.model,
            client_factory=self.client_factory,
            docker_client=self.docker_client,
            with_ui=with_ui,
            ui_bus=ui_bus,
            connection_manager=connection_manager,
            system_override=system,
        )

        agent_runtime = AgentRuntime(agent_id=agent_id, running=running, runtime=runtime)
        self._items[agent_id] = agent_runtime
        return agent_runtime

    async def ensure_live(
        self,
        agent_id: str,
        *,
        with_ui: bool = True,
        ui_bus=None,
        connection_manager=None,
    ) -> AgentRuntime:
        """Return a live agent runtime, starting it from persisted specs if needed.

        Raises KeyError if the agent does not exist in persistence.
        """
        if (agent_runtime := self.get(agent_id)) is not None:
            return agent_runtime

        row = await self.persistence.get_agent(agent_id)
        if row is None:
            raise KeyError(f"agent not found: {agent_id}")

        return await self.create(
            agent_id,
            row.mcp_config,
            with_ui=with_ui,
            ui_bus=ui_bus,
            connection_manager=connection_manager,
        )

    def remove(self, agent_id: str) -> None:
        self._items.pop(agent_id, None)

    async def close_all(self) -> None:
        items = list(self._items.values())
        for agent_runtime in items:
            await agent_runtime.close()
        self._items.clear()
