"""Sidecar implementations for RunningInfrastructure.

Sidecars add optional functionality to the core MCP infrastructure:
- UISidecar: WebSocket UI integration
- ChatSidecar: Persisted conversation history
- LoopControlSidecar: Agent loop control (local agents only)

Each sidecar is composable - attach only what you need.

Note: Docker execution is NOT a sidecar - it's configured via MCPConfig
      as a standard MCP server (stdio transport to docker-exec-mcp).
"""

from __future__ import annotations

from dataclasses import dataclass

from adgn.agent.runtime.running import RunningInfrastructure, Sidecar
from adgn.agent.server.bus import ServerBus
from adgn.mcp._shared.constants import UI_SERVER_NAME
from adgn.mcp.chat.server import attach_persisted_chat_servers
from adgn.mcp.loop.server import make_loop_server
from adgn.mcp.ui.server import make_ui_server


class UISidecar(Sidecar):
    """Sidecar for WebSocket UI integration.

    Provides tools for UI event broadcasting and status updates via WebSocket.

    Args:
        ui_bus: ServerBus for WebSocket communication
    """

    def __init__(self, ui_bus: ServerBus):
        self.ui_bus = ui_bus

    async def attach(self, running: RunningInfrastructure) -> None:
        """Mount UI server into compositor."""
        ui_server = make_ui_server("UI", self.ui_bus)
        await running.compositor.mount_inproc(UI_SERVER_NAME, ui_server)


class ChatSidecar(Sidecar):
    """Sidecar for persisted chat servers.

    Provides conversation history tools (human/assistant messages) scoped
    to the agent_id, persisted in SQLite.
    """

    async def attach(self, running: RunningInfrastructure) -> None:
        """Mount chat servers into compositor."""
        # Chat servers need persistence from approval engine
        await attach_persisted_chat_servers(
            running.compositor,
            persistence=running.approval_engine.persistence,
            agent_id=running.agent_id,
        )


class LoopControlSidecar(Sidecar):
    """Sidecar for agent loop control (local agents only).

    Provides tools for controlling the agent's execution loop (continue,
    abort, etc.). Should NOT be exposed to external agents.
    """

    async def attach(self, running: RunningInfrastructure) -> None:
        """Mount loop control server into compositor."""
        loop_server = make_loop_server("loop")
        await running.compositor.mount_inproc("loop", loop_server)


# ===== Sidecar Bundles (presets) =====


@dataclass
class SidecarBundle:
    """A collection of sidecars to attach together.

    Provides preset bundles for common configurations.

    Note: Docker exec is NOT included in sidecars - configure it via
          MCPConfig as a standard server. See examples in presets.
    """

    sidecars: list[Sidecar]

    @classmethod
    def for_local_agent(cls, ui_bus: ServerBus) -> "SidecarBundle":
        """Sidecars for a local agent: UI, chat, loop.

        Args:
            ui_bus: ServerBus for WebSocket UI

        Note: Add docker exec via MCPConfig if needed:
            {
              "mcpServers": {
                "docker": {
                  "transport": "stdio",
                  "command": "docker-exec-mcp",
                  "args": ["--mount", "/path/to/repo:/workspace:ro"]
                }
              }
            }
        """
        return cls([UISidecar(ui_bus), ChatSidecar(), LoopControlSidecar()])

    @classmethod
    def for_external_agent(cls) -> "SidecarBundle":
        """Sidecars for external agent: none needed.

        External agents should configure docker exec via MCPConfig.
        No UI, chat, or loop control needed for external agents.
        """
        return cls([])

    @classmethod
    def for_testing(cls) -> "SidecarBundle":
        """Minimal sidecars for testing: none.

        Configure docker exec via MCPConfig if needed for tests.
        """
        return cls([])

    async def attach_all(self, running: RunningInfrastructure) -> None:
        """Attach all sidecars in this bundle to the running infrastructure."""
        for sidecar in self.sidecars:
            await running.attach_sidecar(sidecar)
