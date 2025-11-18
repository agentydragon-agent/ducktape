"""Channel bundle - aggregates all channels for an agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from adgn.agent.server.channels.approvals import ApprovalsChannelManager
from adgn.agent.server.channels.mcp import McpChannelManager
from adgn.agent.server.channels.policy import PolicyChannelManager
from adgn.agent.server.channels.session import SessionChannelManager
from adgn.agent.server.channels.ui import UiChannelManager

if TYPE_CHECKING:
    from adgn.agent.runtime.registry import AgentRuntime


@dataclass
class ChannelBundle:
    """Aggregates all channels for an agent.

    Each channel maps to a specific component:
    - session: LocalAgentRuntime.session (optional - only for local agents)
    - mcp: RunningInfrastructure.compositor (always present)
    - approvals: RunningInfrastructure.approval_hub (always present)
    - policy: RunningInfrastructure.approval_engine (always present)
    - ui: AgentRuntime._ui_manager (optional)

    Remote agents (external LLM providers) will have mcp/approvals/policy but no session/ui.
    """

    # Always present (part of RunningInfrastructure)
    mcp: McpChannelManager
    approvals: ApprovalsChannelManager
    policy: PolicyChannelManager

    # Optional (only when components are attached)
    session: SessionChannelManager | None = None
    ui: UiChannelManager | None = None

    @classmethod
    def for_agent_runtime(cls, runtime: AgentRuntime) -> ChannelBundle:
        """Create channel bundle from agent runtime.

        Always creates mcp/approvals/policy channels (infrastructure always present).
        Creates session channel if local runtime has session.
        Creates UI channel if UI manager is attached.
        """
        # Always present channels
        mcp = McpChannelManager()
        approvals = ApprovalsChannelManager()
        policy = PolicyChannelManager()

        # Optional session channel (only for local agents)
        session = None
        if runtime.runtime.session is not None:
            session = SessionChannelManager()
            session.session = runtime.runtime.session

        # Optional UI channel
        ui = None
        if runtime._ui_manager is not None:
            ui = UiChannelManager()

        return cls(
            mcp=mcp,
            approvals=approvals,
            policy=policy,
            session=session,
            ui=ui,
        )

    async def send_initial_snapshots(self, runtime: AgentRuntime) -> None:
        """Send initial state snapshots on all available channels."""
        # MCP snapshot
        await self.mcp.send_snapshot(runtime.running.compositor)

        # Approvals snapshot
        await self.approvals.send_snapshot(runtime.running.approval_hub)

        # Policy snapshot
        await self.policy.send_snapshot(runtime.running.approval_engine)

        # Session snapshot (if available)
        if self.session is not None and runtime.runtime.session is not None:
            await self.session.send_snapshot(runtime.runtime.session)

        # UI snapshot (if available)
        if self.ui is not None and runtime.runtime.session is not None:
            ui_state = runtime.runtime.session.ui_state
            await self.ui.send_state_snapshot(ui_state, ui_state.seq)

    async def flush_all(self) -> None:
        """Flush all channels."""
        await self.mcp.flush()
        await self.approvals.flush()
        await self.policy.flush()
        if self.session is not None:
            await self.session.flush()
        if self.ui is not None:
            await self.ui.flush()
