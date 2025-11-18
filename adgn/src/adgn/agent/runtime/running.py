"""Running MCP infrastructure - type-safe state after initialization.

This module defines RunningInfrastructure, the core MCP infrastructure state
returned by MCPInfrastructure.start(). All fields are non-optional, providing
type-safe access to compositor, policy gateway, and approval infrastructure.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastmcp.client import Client
from fastmcp.mcp_config import MCPServerTypes

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.mcp.approval_policy.clients import PolicyApproverStub, PolicyReaderStub
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifications.buffer import NotificationsBuffer

if TYPE_CHECKING:
    from adgn.agent.runtime.sidecar import Sidecar
    from adgn.mcp.compositor.clients import CompositorAdminClient


@dataclass
class CloseResult:
    drained: bool
    error: str | None = None


@dataclass
class RunningInfrastructure:
    """Obtained by calling MCPInfrastructure.start().

    Sidecars can attach to this infrastructure to add optional functionality
    (UI, chat, loop control, etc.) without coupling to the core.
    """

    # Core MCP infrastructure
    compositor: Compositor
    compositor_client: Client
    notifications_buffer: NotificationsBuffer

    # Approval infrastructure
    policy_reader: PolicyReaderStub
    policy_approver: PolicyApproverStub
    approval_engine: ApprovalPolicyEngine
    approval_hub: ApprovalHub

    # Metadata
    agent_id: str

    # Internal cleanup
    _stack: AsyncExitStack

    # Attached sidecars (for lifecycle management)
    _sidecars: list[Sidecar] = None  # type: ignore

    # Cached clients
    _admin_client: CompositorAdminClient | None = None

    def __post_init__(self) -> None:
        if self._sidecars is None:
            object.__setattr__(self, "_sidecars", [])

    @property
    def admin_client(self) -> CompositorAdminClient:
        """Get or create compositor admin client."""
        if self._admin_client is None:
            from adgn.mcp.compositor.clients import CompositorAdminClient

            object.__setattr__(self, "_admin_client", CompositorAdminClient(self.compositor_client))
        assert self._admin_client is not None  # for mypy
        return self._admin_client

    async def attach_sidecar(self, sidecar: Sidecar) -> None:
        """Sidecars are detached in reverse order when close() is called."""
        await sidecar.attach(self)
        self._sidecars.append(sidecar)

    async def close(self) -> CloseResult:
        """Sidecars are detached in reverse order of attachment."""
        errors: list[str] = []

        # Detach sidecars in reverse order
        for sidecar in reversed(self._sidecars):
            try:
                await sidecar.detach()
            except Exception as e:
                errors.append(f"{type(sidecar).__name__}: {e}")

        # Close async exit stack
        try:
            await self._stack.aclose()
        except Exception as e:
            errors.append(f"stack: {e}")

        if errors:
            return CloseResult(drained=False, error="; ".join(errors))
        return CloseResult(drained=True)

    async def attach_mcp(self, name: str, spec: MCPServerTypes) -> None:
        """Policy-gated via active approval policy."""
        await self.admin_client.attach_server(name=name, spec=spec)

    async def detach_mcp(self, name: str) -> None:
        """Policy-gated via active approval policy."""
        await self.admin_client.detach_server(name=name)

    async def __aenter__(self) -> RunningInfrastructure:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
