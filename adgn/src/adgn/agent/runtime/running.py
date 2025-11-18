"""Running MCP infrastructure - type-safe state after initialization.

This module defines RunningInfrastructure, the core MCP infrastructure state
returned by MCPInfrastructure.start(). All fields are non-optional, providing
type-safe access to compositor, policy gateway, and approval infrastructure.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass

from fastmcp.client import Client
from fastmcp.mcp_config import MCPServerTypes

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.persist import ApprovalOutcome
from adgn.mcp.approval_policy.clients import PolicyApproverStub, PolicyReaderStub
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifications.buffer import NotificationsBuffer


@dataclass
class CloseResult:
    """Result of closing infrastructure."""

    drained: bool
    error: str | None = None


@dataclass
class RunningInfrastructure:
    """Running MCP infrastructure - all components initialized and non-optional.

    Obtained by calling MCPInfrastructure.start(). Provides type-safe access
    to all infrastructure components without Optional checks.

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
    _sidecars: list["Sidecar"] = None  # type: ignore

    def __post_init__(self) -> None:
        """Initialize mutable fields."""
        if self._sidecars is None:
            object.__setattr__(self, "_sidecars", [])

    async def attach_sidecar(self, sidecar: "Sidecar") -> None:
        """Attach a sidecar to this running infrastructure.

        The sidecar's attach() method will be called immediately, and it
        will be detached in reverse order when close() is called.
        """
        await sidecar.attach(self)
        self._sidecars.append(sidecar)

    async def close(self) -> CloseResult:
        """Shutdown infrastructure and all attached sidecars.

        Sidecars are detached in reverse order of attachment.
        """
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
        """Attach an MCP server at runtime via compositor_admin.

        This is policy-gated - the active approval policy will decide whether
        to allow the attachment.
        """
        from adgn.mcp.compositor.clients import CompositorAdminClient

        admin = CompositorAdminClient(self.compositor_client)
        await admin.attach_server(name=name, spec=spec)

    async def detach_mcp(self, name: str) -> None:
        """Detach an MCP server at runtime via compositor_admin.

        This is policy-gated - the active approval policy will decide whether
        to allow the detachment.
        """
        from adgn.mcp.compositor.clients import CompositorAdminClient

        admin = CompositorAdminClient(self.compositor_client)
        await admin.detach_server(name=name)

    async def __aenter__(self) -> "RunningInfrastructure":
        """Support async context manager protocol."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Cleanup on context manager exit."""
        await self.close()


# Sidecar protocol imported here to avoid circular imports
from abc import ABC, abstractmethod


class Sidecar(ABC):
    """A plugin that attaches to RunningInfrastructure.

    Sidecars add optional functionality (UI, chat, loop, runtime exec)
    without being tightly coupled to the core infrastructure.

    Each sidecar is responsible for:
    - Mounting its MCP servers into the compositor during attach()
    - Cleaning up resources during detach()
    """

    @abstractmethod
    async def attach(self, running: RunningInfrastructure) -> None:
        """Attach this sidecar to running infrastructure.

        This method should mount any MCP servers into running.compositor
        and perform any other initialization needed.
        """
        pass

    async def detach(self) -> None:
        """Cleanup when infrastructure is closing (optional override)."""
        pass
