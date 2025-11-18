from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from docker import DockerClient
from fastmcp.mcp_config import MCPConfig, MCPServerTypes

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.local_runtime import LocalAgentRuntime
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.runtime import ConnectionManager
from adgn.mcp.compositor.clients import CompositorAdminClient, CompositorMetaClient
from adgn.openai_utils.model import OpenAIModelProto

from .builder import build_local_agent


@dataclass
class UiFacet:
    """UI manager + bus wrapper for backward compatibility."""
    manager: ConnectionManager
    ui_bus: ServerBus


@dataclass
class AgentRuntime:
    """Combines infrastructure and runtime for a running agent.

    - RunningInfrastructure: Core MCP + policy gateway
    - LocalAgentRuntime: MiniCodex agent
    """

    agent_id: str
    running: RunningInfrastructure
    runtime: LocalAgentRuntime
    _ui_manager = None  # Set from builder if UI attached
    _ui_bus = None  # Set from builder if UI attached

    @property
    def ui(self):
        """UI facet for backward compatibility."""
        if self._ui_manager is None or self._ui_bus is None:
            return None
        return UiFacet(manager=self._ui_manager, ui_bus=self._ui_bus)

    @property
    def session(self):
        """Agent session from runtime."""
        return self.runtime.session

    @property
    def policy_approver(self):
        """Policy approver stub from infrastructure."""
        return self.running.policy_approver

    @property
    def compositor_client(self):
        """Compositor client from infrastructure."""
        return self.running.compositor_client

    @property
    def runtime_ephemeral(self):
        """Runtime ephemeral flag (always False for new architecture)."""
        return False

    async def list_mcp_entries(self):
        """List MCP server entries via compositor_meta."""
        meta = CompositorMetaClient(self.running.compositor_client)
        return await meta.list_states()

    async def close(self):
        """Close both runtime and infrastructure."""
        await self.runtime.close()
        result = await self.running.close()
        return {"drained": result.drained, "error": result.error}

    async def reconfigure_mcp(
        self,
        *,
        mcp_config: MCPConfig | None = None,
        attach: dict[str, MCPConfig] | None = None,
        detach: list[str] | None = None,
    ) -> None:
        """Reconfigure MCP servers at runtime."""
        admin = CompositorAdminClient(self.running.compositor_client)
        current_specs = await self.running.compositor.mount_specs()

        # Full replace
        if mcp_config is not None:
            desired = mcp_config.mcpServers or {}
            # Detach missing
            miss = list(set(current_specs.keys()) - set(desired.keys()))
            if miss:
                await asyncio.gather(*(admin.detach_server(name=n) for n in miss))
            # Attach new or changed
            attach_args: list[tuple[str, MCPServerTypes]] = []
            for name, spec in desired.items():
                prev = current_specs.get(name)
                if prev is None or prev.model_dump(mode="json") != spec.model_dump(mode="json"):
                    attach_args.append((name, spec))
            if attach_args:
                await asyncio.gather(*(admin.attach_server(name=n, spec=s) for (n, s) in attach_args))

        # Incremental detach
        if detach:
            await asyncio.gather(*(admin.detach_server(name=n) for n in detach))

        # Incremental attach
        if attach:
            for _, cfg in attach.items():
                latest_specs = await self.running.compositor.mount_specs()
                attach_args2: list[tuple[str, MCPServerTypes]] = []
                for name, spec in (cfg.mcpServers or {}).items():
                    prev = latest_specs.get(name)
                    if prev is None or prev.model_dump(mode="json") != spec.model_dump(mode="json"):
                        attach_args2.append((name, spec))
                if attach_args2:
                    await asyncio.gather(*(admin.attach_server(name=n, spec=s) for (n, s) in attach_args2))

    async def attach_mcp(self, name: str, spec: MCPServerTypes) -> None:
        """Attach a single MCP server (policy-gated)."""
        await self.running.attach_mcp(name, spec)

    async def detach_mcp(self, name: str) -> None:
        """Detach a single MCP server (policy-gated)."""
        await self.running.detach_mcp(name)

    async def sampling_snapshot(self):
        """Get sampling snapshot from compositor."""
        return await self.running.compositor.sampling_snapshot()

    async def sampling_snapshot_incremental(self) -> None:
        """Send incremental sampling snapshot to UI."""
        if not self.ui or not self.session:
            return
        snap = await self.running.compositor.sampling_snapshot()
        await self.ui.manager.send_payload(await self.session.build_snapshot(sampling=snap))


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
        # Create ui_bus if needed for UI
        if with_ui and ui_bus is None:
            ui_bus = ServerBus()

        running, runtime, ui_bus_out, conn_mgr_out = await build_local_agent(
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
        # Set UI components for backward compatibility
        agent_runtime._ui_manager = conn_mgr_out
        agent_runtime._ui_bus = ui_bus_out
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
        """Raises KeyError if the agent does not exist in persistence."""
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
