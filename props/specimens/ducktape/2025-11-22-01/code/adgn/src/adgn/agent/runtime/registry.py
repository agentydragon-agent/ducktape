from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from docker.client import DockerClient
from fastmcp.mcp_config import MCPConfig

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.local_runtime import LocalAgentRuntime
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.runtime import ConnectionManager
from adgn.agent.types import AgentID
from adgn.openai_utils.model import OpenAIModelProto

from .builder import build_local_agent


@dataclass
class AgentRuntime:
    """Holds components for a running local agent.

    Components:
    - running: Infrastructure (MCP + policy gateway)
    - runtime: Local agent (MiniCodex + session)
    - _ui_manager: WebSocket connection manager (optional)
    - _ui_bus: UI event bus (optional)

    This is a pure data holder for lifecycle management only.
    Handlers access components directly (e.g., container.running.compositor).
    """

    agent_id: AgentID
    running: RunningInfrastructure
    runtime: LocalAgentRuntime
    _ui_manager: ConnectionManager | None = None
    _ui_bus: ServerBus | None = None

    async def close(self):
        """Lifecycle management - close all components together."""
        await self.runtime.close()
        return await self.running.close()


@dataclass
class AgentRegistry:
    """Registry for managing agent runtimes.

    Uses MCPInfrastructure + LocalAgentRuntime architecture for
    clean separation between infrastructure and agent layers.
    """

    persistence: SQLitePersistence
    model: str
    client_factory: Callable[[str], OpenAIModelProto]
    docker_client: DockerClient
    _items: dict[AgentID, AgentRuntime] = field(default_factory=dict)

    def get(self, agent_id: AgentID) -> AgentRuntime | None:
        return self._items.get(agent_id)

    def list(self) -> list[AgentRuntime]:
        return list(self._items.values())

    async def create(
        self, agent_id: AgentID, mcp_config: MCPConfig, *, with_ui: bool = True, system: str | None = None
    ) -> AgentRuntime:
        running, runtime, ui_bus_out, conn_mgr_out = await build_local_agent(
            agent_id=agent_id,
            mcp_config=mcp_config,
            persistence=self.persistence,
            model=self.model,
            client_factory=self.client_factory,
            docker_client=self.docker_client,
            with_ui=with_ui,
            system_override=system,
        )

        agent_runtime = AgentRuntime(agent_id=agent_id, running=running, runtime=runtime)
        # Set UI components for backward compatibility
        agent_runtime._ui_manager = conn_mgr_out
        agent_runtime._ui_bus = ui_bus_out
        self._items[agent_id] = agent_runtime
        return agent_runtime

    async def ensure_live(self, agent_id: AgentID, *, with_ui: bool = True) -> AgentRuntime:
        """Raises KeyError if the agent does not exist in persistence."""
        if (agent_runtime := self.get(agent_id)) is not None:
            return agent_runtime

        if (row := await self.persistence.get_agent(agent_id)) is None:
            raise KeyError(f"agent not found: {agent_id}")

        return await self.create(agent_id, row.mcp_config, with_ui=with_ui)

    def remove(self, agent_id: AgentID) -> None:
        self._items.pop(agent_id, None)

    async def close_all(self) -> None:
        items = list(self._items.values())
        for agent_runtime in items:
            await agent_runtime.close()
        self._items.clear()
