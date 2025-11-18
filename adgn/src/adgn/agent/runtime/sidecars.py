"""Sidecar implementations for RunningInfrastructure.

Sidecars add optional functionality to the core MCP infrastructure:
- RuntimeExecSidecar: Docker-based code execution
- UISidecar: WebSocket UI integration
- ChatSidecar: Persisted conversation history
- LoopControlSidecar: Agent loop control (local agents only)

Each sidecar is composable - attach only what you need.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from adgn.agent.runtime.images import resolve_runtime_image
from adgn.agent.runtime.running import RunningInfrastructure, Sidecar
from adgn.agent.server.bus import ServerBus
from adgn.mcp._shared.constants import (
    RUNTIME_EXEC_TOOL_NAME,
    RUNTIME_SERVER_NAME,
    UI_SERVER_NAME,
)
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.mcp.chat.server import attach_persisted_chat_servers
from adgn.mcp.loop.server import make_loop_server
from adgn.mcp.runtime.server import make_runtime_server
from adgn.mcp.ui.server import make_ui_server


class RuntimeExecSidecar(Sidecar):
    """Sidecar for Docker-based runtime execution.

    Provides a policy-gated `runtime_exec` tool that runs commands in
    isolated Docker containers.

    Args:
        runtime_image: Docker image to use (default: resolve from config)
        mount_repo: Whether to mount the repository into containers
        repo_path: Path to repository (default: current working directory)
        repo_bind: Container path to bind repo to (default: /workspace)
        repo_mode: Mount mode - 'rw' or 'ro' (default: ro for safety)
        scratch_path: Optional writable scratch directory in repo
        scratch_bind: Container path for scratch directory (default: /scratch)
    """

    def __init__(
        self,
        runtime_image: str | None = None,
        mount_repo: bool = False,
        repo_path: Path | None = None,
        repo_bind: str = "/workspace",
        repo_mode: str = "ro",
        scratch_path: Path | None = None,
        scratch_bind: str = "/scratch",
    ):
        self.runtime_image = runtime_image
        self.mount_repo = mount_repo
        self.repo_path = repo_path
        self.repo_bind = repo_bind
        self.repo_mode = repo_mode
        self.scratch_path = scratch_path
        self.scratch_bind = scratch_bind

    async def attach(self, running: RunningInfrastructure) -> None:
        """Mount runtime exec server into compositor."""
        image = self.runtime_image or resolve_runtime_image()

        # Build volumes configuration
        volumes = None
        if self.mount_repo:
            repo = self.repo_path or Path.cwd()
            volumes = {
                str(repo): {
                    "bind": self.repo_bind,
                    "mode": self.repo_mode,
                }
            }

            # Add writable scratch directory if specified
            if self.scratch_path:
                scratch = repo / self.scratch_path
                scratch.mkdir(parents=True, exist_ok=True)
                volumes[str(scratch)] = {
                    "bind": self.scratch_bind,
                    "mode": "rw",
                }

        opts = ContainerOptions(
            image=image,
            volumes=volumes,
            ephemeral=True,
        )

        runtime_server = make_runtime_server(opts)

        # Verify expected tool name
        tools = await runtime_server._tool_manager.list_tools()
        assert RUNTIME_EXEC_TOOL_NAME in [t.name for t in tools], \
            f"Expected tool {RUNTIME_EXEC_TOOL_NAME} not found in runtime server"

        await running.compositor.mount_inproc(RUNTIME_SERVER_NAME, runtime_server)


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
    """

    sidecars: list[Sidecar]

    @classmethod
    def for_local_agent(
        cls,
        ui_bus: ServerBus,
        mount_repo: bool = False,
        repo_path: Path | None = None,
    ) -> "SidecarBundle":
        """Sidecars for a local agent: runtime, UI, chat, loop.

        Args:
            ui_bus: ServerBus for WebSocket UI
            mount_repo: Whether to mount repository into runtime containers
            repo_path: Path to repository (default: cwd)
        """
        return cls(
            [
                RuntimeExecSidecar(
                    mount_repo=mount_repo,
                    repo_path=repo_path,
                    repo_mode="ro",  # Read-only for safety
                    scratch_path=Path(".agent-scratch") if mount_repo else None,
                ),
                UISidecar(ui_bus),
                ChatSidecar(),
                LoopControlSidecar(),
            ]
        )

    @classmethod
    def for_external_agent(
        cls,
        mount_repo: bool = False,
        repo_path: Path | None = None,
        repo_mode: str = "ro",
    ) -> "SidecarBundle":
        """Sidecars for external agent: just runtime.

        Args:
            mount_repo: Whether to mount repository into runtime containers
            repo_path: Path to repository (default: cwd)
            repo_mode: Mount mode - 'ro' (recommended) or 'rw'
        """
        return cls(
            [
                RuntimeExecSidecar(
                    mount_repo=mount_repo,
                    repo_path=repo_path,
                    repo_mode=repo_mode,
                    scratch_path=Path(".agent-scratch") if mount_repo else None,
                )
            ]
        )

    @classmethod
    def for_testing(cls, mount_repo: bool = False) -> "SidecarBundle":
        """Minimal sidecars for testing: just runtime.

        Args:
            mount_repo: Whether to mount repository (usually False for tests)
        """
        return cls([RuntimeExecSidecar(mount_repo=mount_repo)])

    async def attach_all(self, running: RunningInfrastructure) -> None:
        """Attach all sidecars in this bundle to the running infrastructure."""
        for sidecar in self.sidecars:
            await running.attach_sidecar(sidecar)
