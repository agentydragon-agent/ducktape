"""Running MCP infrastructure - type-safe state after initialization.

This module defines RunningInfrastructure, the core MCP infrastructure state
returned by MCPInfrastructure.start(). All fields are non-optional, providing
type-safe access to compositor, policy gateway, and approval infrastructure.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from fastmcp.client import Client
from fastmcp.mcp_config import MCPServerTypes

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.mcp.approval_policy.clients import PolicyApproverStub, PolicyReaderStub
from adgn.mcp.compositor.clients import CompositorAdminClient
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifications.buffer import NotificationsBuffer

if TYPE_CHECKING:
    from adgn.agent.runtime.sidecar import Sidecar


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

    @cached_property
    def admin_client(self) -> CompositorAdminClient:
        """Get or create compositor admin client."""
        return CompositorAdminClient(self.compositor_client)

    async def attach_sidecar(self, sidecar: Sidecar) -> None:
        """Attach a sidecar to this infrastructure."""
        await sidecar.attach(self)

    async def close(self) -> CloseResult:
        """Close the infrastructure and cleanup resources."""
        errors: list[str] = []

        # Close async exit stack
        try:
            await self._stack.aclose()
        except Exception as e:
            errors.append(f"stack: {e}")

        if errors:
            return CloseResult(drained=False, error="; ".join(errors))
        return CloseResult(drained=True)

    async def __aenter__(self) -> RunningInfrastructure:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
