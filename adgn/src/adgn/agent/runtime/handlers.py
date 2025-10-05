from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from adgn.agent.approvals import (
    ApprovalHub,
    ApprovalPolicyEngine,
    ApprovalPolicyHandler,
)
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.persist import ApprovalOutcome, Persistence
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.agent.server.protocol import ApprovalPendingEvt
from adgn.agent.server.runtime import ConnectionManager


def build_handlers(
    *,
    mcp: McpManager,
    manager: ConnectionManager,
    persistence: Persistence,
    approval_engine: ApprovalPolicyEngine,
    approval_hub: ApprovalHub,
    get_run_id: Callable[[], str | None],
    ui_bus: ServerBus | None = None,
) -> tuple[list[BaseHandler], RunPersistenceHandler, ApprovalPolicyHandler]:
    """Construct the standard handler stack for an agent.

    Returns (handlers, persist_handler, policy_handler).
    """
    policy_handler = ApprovalPolicyHandler(approval_engine, approval_hub)

    async def _record(call_id: str, tool_key: str, outcome: ApprovalOutcome) -> None:
        rid = get_run_id()
        assert rid is not None
        await persistence.record_approval(
            run_id=rid,
            agent_id=None,
            call_id=call_id,
            tool_key=tool_key,
            outcome=outcome,
            decided_at=datetime.now(UTC),
        )

    policy_handler.set_policy_outcome_recorder(_record, get_run_id)

    async def _notify_pending(call_id: str, tool_key: str, args_json: str | None) -> None:
        await manager.send_payload(
            ApprovalPendingEvt(call_id=call_id, tool_key=tool_key, args_json=args_json)
        )

    policy_handler.set_pending_notifier(_notify_pending)

    persist_handler = RunPersistenceHandler(persistence=persistence, get_run_id=get_run_id)
    handlers: list[BaseHandler] = [policy_handler, manager, persist_handler]
    if ui_bus is not None:
        handlers.extend(
            [
                ServerModeHandler(bus=ui_bus, poll_notifications=mcp.poll_notifications),
                DisplayEventsHandler(),
            ]
        )
    return handlers, persist_handler, policy_handler
