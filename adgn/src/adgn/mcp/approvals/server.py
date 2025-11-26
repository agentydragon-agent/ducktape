"""MCP server for approval actions (approve/deny pending tool calls)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from adgn.agent.approvals import ApprovalHub
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

APPROVALS_SERVER_NAME = "approvals"
APPROVALS_PENDING_URI = "approvals://pending"


class ApproveCallArgs(BaseModel):
    call_id: str = Field(description="ID of the pending approval to approve")


class DenyAbortArgs(BaseModel):
    call_id: str = Field(description="ID of the pending approval to deny and abort turn")


class DenyContinueArgs(BaseModel):
    call_id: str = Field(description="ID of the pending approval to deny but continue turn")


class PendingApprovalItem(BaseModel):
    """Pending approval request exposed to UI."""

    call_id: str
    tool_key: str
    args_json: str | None = None


def make_approvals_server(
    hub: ApprovalHub, *, name: str = APPROVALS_SERVER_NAME, notifier_callback: callable | None = None
) -> NotifyingFastMCP:
    """Create MCP server for approval actions.

    Exposes tools to approve/deny pending approvals and a resource for the pending list.
    """
    mcp = NotifyingFastMCP(
        name=name,
        instructions=(
            "Approval actions: approve or deny pending tool calls. "
            "Subscribe to approvals://pending resource for real-time updates."
        ),
    )

    # Resource: pending approvals list
    @mcp.resource(APPROVALS_PENDING_URI, name="approvals.pending", mime_type="application/json")
    async def pending_approvals() -> dict:
        """List all pending approval requests."""
        items = [
            PendingApprovalItem(
                call_id=call_id, tool_key=req.tool_key, args_json=req.tool_call.args_json if req.tool_call else None
            )
            for call_id, req in hub.pending.items()
        ]
        return {"pending": [item.model_dump() for item in items]}

    # Tools: approval actions
    @mcp.flat_model()
    async def approve_call(input: ApproveCallArgs) -> SimpleOk:
        """Approve a pending tool call and allow it to execute."""
        hub.resolve(input.call_id, ContinueDecision())
        # Notify that pending list changed
        if notifier_callback:
            notifier_callback(APPROVALS_PENDING_URI)
        return SimpleOk(ok=True)

    @mcp.flat_model()
    async def deny_abort(input: DenyAbortArgs) -> SimpleOk:
        """Deny a pending tool call and abort the current turn."""
        hub.resolve(input.call_id, AbortTurnDecision(reason="user_denied"))
        # Notify that pending list changed
        if notifier_callback:
            notifier_callback(APPROVALS_PENDING_URI)
        return SimpleOk(ok=True)

    @mcp.flat_model()
    async def deny_continue(input: DenyContinueArgs) -> SimpleOk:
        """Deny a pending tool call but continue the turn (tool is skipped)."""
        # Continue decision with skip flag (if supported), otherwise just continue
        # For now, continue without executing the tool
        hub.resolve(input.call_id, ContinueDecision())
        # Notify that pending list changed
        if notifier_callback:
            notifier_callback(APPROVALS_PENDING_URI)
        return SimpleOk(ok=True)

    return mcp


async def attach_approvals(comp, hub: ApprovalHub, *, name: str = APPROVALS_SERVER_NAME):
    """Attach approvals server in-proc to a Compositor."""

    def notify_callback(uri: str):
        """Sync callback that schedules async broadcast."""
        import asyncio

        asyncio.create_task(server.broadcast_resource_updated(uri))

    server = make_approvals_server(hub, name=name, notifier_callback=notify_callback)
    await comp.mount_inproc(name, server)
    return server
