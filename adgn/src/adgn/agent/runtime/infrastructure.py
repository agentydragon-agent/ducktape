"""MCPInfrastructure - builder for core MCP infrastructure.

This module provides MCPInfrastructure, a factory/builder that creates
RunningInfrastructure instances. The infrastructure includes:

- Compositor (MCP server aggregator)
- Policy Gateway (approval enforcement middleware)
- Approval Policy Engine (Docker-based policy evaluation)
- Standard meta servers (resources, compositor_meta, compositor_admin)

Sidecars (runtime, UI, chat, loop) are attached separately to RunningInfrastructure.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from datetime import UTC, datetime
import json
import logging
import os

from docker import DockerClient
from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig

from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine, load_default_policy_source, make_policy_engine
from adgn.agent.persist import ApprovalOutcome
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.presets import discover_presets
from adgn.agent.runtime.running import RunningInfrastructure
from adgn.agent.server.protocol import ApprovalBrief, ApprovalPendingEvt
from adgn.agent.server.runtime import ConnectionManager
from adgn.agent.types import AgentID
from adgn.mcp._shared.constants import (
    APPROVAL_POLICY_SERVER_NAME_APPROVER,
    APPROVAL_POLICY_SERVER_NAME_PROPOSER,
    APPROVAL_POLICY_SERVER_NAME_READER,
)
from adgn.mcp.approval_policy.clients import PolicyApproverStub, PolicyReaderStub
from adgn.mcp.approval_policy.server import (
    ApprovalPolicyAdminServer,
    ApprovalPolicyProposerServer,
    ApprovalPolicyServer,
)
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifications.buffer import NotificationsBuffer
from adgn.mcp.policy_gateway.middleware import install_policy_gateway
from adgn.mcp.stubs.typed_stubs import TypedClient

logger = logging.getLogger(__name__)


class MCPInfrastructure:
    """Creates minimal core infrastructure - does NOT include optional sidecars
    (UI, chat, loop, runtime). Those are attached to RunningInfrastructure.

    Example:
        # Create builder
        builder = MCPInfrastructure(
            agent_id="my-agent",
            persistence=persistence,
            docker_client=docker_client,
        )

        # Start core infrastructure
        running = await builder.start(mcp_config)

        # Attach sidecars
        from adgn.agent.runtime.sidecars import SidecarBundle
        bundle = SidecarBundle.for_local_agent(ui_bus=ui_bus)
        await bundle.attach_all(running)

        # Use it
        tools = await running.compositor_client.list_tools()

        # Cleanup
        await running.close()
    """

    def __init__(
        self,
        agent_id: AgentID,
        persistence: SQLitePersistence,
        docker_client: DockerClient,
        initial_policy: str | None = None,
        connection_manager: ConnectionManager | None = None,
    ):
        self.agent_id = agent_id
        self.persistence = persistence
        self.docker_client = docker_client
        self.initial_policy = initial_policy
        self._connection_manager = connection_manager

    async def start(self, mcp_config: MCPConfig) -> RunningInfrastructure:
        stack = AsyncExitStack()
        await stack.__aenter__()

        try:
            # Phase 1: Approval infrastructure
            approval_engine, approval_hub = await self._setup_approval_infrastructure()

            # Phase 2: Create compositor with external servers
            compositor = Compositor("compositor", eager_open=True)
            for name, server_cfg in mcp_config.mcpServers.items():
                await compositor.mount_server(name, server_cfg)

            # Phase 3: Create client and notifications
            notif_buffer = NotificationsBuffer(compositor=compositor)
            compositor_client = Client(compositor, message_handler=notif_buffer.handler)
            await stack.enter_async_context(compositor_client)

            # Phase 4: Mount approval policy servers
            policy_reader, policy_approver = await self._mount_approval_policy_servers(
                compositor, approval_engine, stack
            )

            # Phase 5: Install policy gateway
            await self._install_policy_gateway(compositor, approval_hub, policy_reader)

            # Phase 6: Mount standard meta servers (resources, compositor_meta, compositor_admin)
            await mount_standard_inproc_servers(compositor=compositor, gateway_client=compositor_client)

            return RunningInfrastructure(
                compositor=compositor,
                compositor_client=compositor_client,
                notifications_buffer=notif_buffer,
                policy_reader=policy_reader,
                policy_approver=policy_approver,
                approval_engine=approval_engine,
                approval_hub=approval_hub,
                agent_id=self.agent_id,
                _stack=stack,
            )

        except Exception:
            # Cleanup on failure
            await stack.aclose()
            raise

    async def _setup_approval_infrastructure(self) -> tuple[ApprovalPolicyEngine, ApprovalHub]:
        """Resolves the initial policy source (from preset, initial_policy parameter,
        or default) and constructs the approval policy engine.
        """
        # Resolve initial policy source via preset/persistence/override
        row = await self.persistence.get_agent(self.agent_id)
        preset_name: str | None = None
        if row and row.metadata is not None:
            preset_name = row.metadata.preset

        presets = discover_presets(os.getenv("ADGN_AGENT_PRESETS_DIR")) if preset_name else {}
        preset = presets.get(preset_name) if preset_name else None

        chosen = (
            self.initial_policy
            or (preset.approval_policy if (preset and preset.approval_policy) else None)
            or load_default_policy_source()
        )

        # Construct the approval engine with the chosen initial policy
        approval_engine = make_policy_engine(
            agent_id=self.agent_id, persistence=self.persistence, docker_client=self.docker_client, policy_source=chosen
        )

        # Create approval hub
        approval_hub = ApprovalHub()

        return (approval_engine, approval_hub)

    async def _mount_approval_policy_servers(
        self, compositor: Compositor, approval_engine: ApprovalPolicyEngine, stack: AsyncExitStack
    ) -> tuple[PolicyReaderStub, PolicyApproverStub]:
        """Mounts:
            - approval_policy_reader (resources + decide tool)
            - approval_policy_proposer (create/withdraw proposal tools)

        Creates internal clients (not mounted):
            - policy_reader: for policy gateway middleware
            - policy_approver: for HTTP admin API
        """
        # Create and mount reader server
        reader_server = ApprovalPolicyServer(approval_engine, name=APPROVAL_POLICY_SERVER_NAME_READER)
        await compositor.mount_inproc(APPROVAL_POLICY_SERVER_NAME_READER, reader_server)

        # Create and mount proposer server
        proposer_server = ApprovalPolicyProposerServer(
            engine=approval_engine, name=APPROVAL_POLICY_SERVER_NAME_PROPOSER
        )
        await compositor.mount_inproc(APPROVAL_POLICY_SERVER_NAME_PROPOSER, proposer_server)

        # Create approver server (admin only, not mounted in compositor)
        approver_server = ApprovalPolicyAdminServer(engine=approval_engine, name=APPROVAL_POLICY_SERVER_NAME_APPROVER)

        # Create internal client to reader for policy gateway
        reader_client = Client(reader_server)
        await stack.enter_async_context(reader_client)
        policy_reader = PolicyReaderStub(TypedClient(reader_client))

        # Create internal client to approver for admin API
        approver_client = Client(approver_server)
        await stack.enter_async_context(approver_client)
        policy_approver = PolicyApproverStub(TypedClient(approver_client))

        return (policy_reader, policy_approver)

    async def _install_policy_gateway(
        self, compositor: Compositor, approval_hub: ApprovalHub, policy_reader: PolicyReaderStub
    ) -> None:
        """The policy gateway intercepts all tool calls and evaluates them
        against the active approval policy before execution.
        """

        async def _pending_notifier(call_id: str, tool_key: str, args_json: str | None) -> None:
            """Notify UI of pending approval requests."""
            if self._connection_manager is not None:
                args = json.loads(args_json) if args_json else {}
                await self._connection_manager.send_payload(
                    ApprovalPendingEvt(approval=ApprovalBrief(call_id=call_id, tool_key=tool_key, args=args))
                )

        async def _record_outcome(call_id: str, tool_key: str, outcome: ApprovalOutcome) -> None:
            """Record approval outcome to persistence.

            Note: run_id is None since policy gateway doesn't have run context.
            Approvals are still recorded for audit/analytics purposes.
            """
            from adgn.agent.persist import Decision

            decision = Decision(outcome=outcome, decided_at=datetime.now(UTC), reason=None)
            await self.persistence.record_approval(
                run_id=None,
                agent_id=self.agent_id,
                call_id=call_id,
                tool_key=tool_key,
                decision=decision,
            )

        install_policy_gateway(
            compositor,
            hub=approval_hub,
            pending_notifier=_pending_notifier,
            record_outcome=_record_outcome,
            policy_reader=policy_reader,
        )
