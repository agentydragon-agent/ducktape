"""Running MCP infrastructure - type-safe state after initialization.

This module defines RunningInfrastructure, the core MCP infrastructure state
returned by MCPInfrastructure.start(). All fields are non-optional, providing
type-safe access to compositor, policy gateway, and approval infrastructure.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

from fastmcp.client import Client

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.types import AgentID
from adgn.mcp.approval_policy.clients import PolicyApproverStub, PolicyReaderStub
from adgn.mcp.compositor.clients import CompositorAdminClient
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifications.buffer import NotificationsBuffer

if TYPE_CHECKING:
    from adgn.agent.runtime.sidecar import Sidecar


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
    agent_id: AgentID

    # Internal cleanup
    _stack: AsyncExitStack

    # Attached sidecars (for lifecycle management)
    _sidecars: list[Sidecar] = field(default_factory=list)

    @cached_property
    def admin_client(self) -> CompositorAdminClient:
        """Get or create compositor admin client."""
        return CompositorAdminClient(self.compositor_client)

    async def attach_sidecar(self, sidecar: Sidecar) -> None:
        """Sidecars are detached in reverse order when close() is called."""
        await sidecar.attach(self)
        self._sidecars.append(sidecar)

    async def close(self) -> None:
        """Sidecars are detached in reverse order of attachment."""
        exceptions: list[Exception] = []

        # Detach sidecars in reverse order
        for sidecar in reversed(self._sidecars):
            try:
                await sidecar.detach()
            except Exception as e:
                exceptions.append(e)

        # Close async exit stack
        try:
            await self._stack.aclose()
        except Exception as e:
            exceptions.append(e)

        if exceptions:
            raise ExceptionGroup("Failed to close infrastructure", exceptions)

    async def __aenter__(self) -> RunningInfrastructure:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
