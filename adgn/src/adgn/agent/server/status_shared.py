from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from adgn.mcp._shared.constants import RUNTIME_CONTAINER_INFO_URI
from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp._shared.types import ContainerInfo
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry


class RunPhase(StrEnum):
    IDLE = "idle"
    SAMPLING = "sampling"
    WAITING_TOOL = "waiting_tool"
    TOOLS_RUNNING = "tools_running"
    WAITING_APPROVAL = "waiting_approval"
    SENDING_OUTPUT = "sending_output"
    ERROR = "error"


def derive_run_phase(*, pending_approvals: int) -> RunPhase:
    """Coarse run phase derivation used by HTTP and WS status.

    - idle: no pending approvals (no activity)
    - waiting_approval: pending approvals exist
    - sampling: default (activity but no pending approvals)
    """
    if pending_approvals > 0:
        return RunPhase.WAITING_APPROVAL
    return RunPhase.IDLE


def determine_run_phase(*, pending_approvals: int, mcp_has_inflight: bool) -> RunPhase:
    """Precise run phase from live signals.

    - IDLE: no pending approvals and no MCP inflight
    - WAITING_APPROVAL: approvals pending
    - TOOLS_RUNNING: MCP policy gateway has in-flight requests
    - SAMPLING: has activity but not in other states
    """
    if pending_approvals > 0:
        return RunPhase.WAITING_APPROVAL
    if mcp_has_inflight:
        return RunPhase.TOOLS_RUNNING
    return RunPhase.IDLE


class AgentLifecycle(StrEnum):
    PERSISTED_ONLY = "persisted_only"
    STARTING = "starting"
    READY = "ready"


"""Status models and builder (no host volumes reported)."""


class UiStateLite(BaseModel):
    ready: bool
    model_config = ConfigDict(extra="forbid")


class ContainerState(BaseModel):
    present: bool
    id: str | None
    ephemeral: bool
    model_config = ConfigDict(extra="forbid")


class AgentStatusCore(BaseModel):
    id: str
    live: bool
    lifecycle: AgentLifecycle
    run_phase: RunPhase
    ui: UiStateLite
    container: ContainerState
    last_event_at: datetime | None = None
    model_config = ConfigDict(extra="forbid")


async def build_agent_status_core(app: FastAPI, agent_id: str) -> AgentStatusCore:
    """Shared builder for agent status used by HTTP and WS paths.

    Computes policy presence/version, MCP server states, lifecycle,
    container id (for non-ephemeral runtime), pending approvals, and run phase.
    """
    registry = app.state.registry
    persistence = app.state.persistence

    c = registry.get(agent_id)
    present = c is not None

    # UI + pending approvals
    ui_ready = bool(c and c.ui is not None)
    pending = 0
    if c and c.session is not None:
        pending = len(c.session.approval_hub.pending)

    # MCP server entries — read via compositor_meta resources through container
    entries: dict[str, ServerEntry] = {}
    if c:
        entries = await c.list_mcp_entries()

    # Lifecycle
    if not present:
        lifecycle = AgentLifecycle.PERSISTED_ONLY
    else:
        lifecycle = AgentLifecycle.STARTING
        # READY when UI ready and all running (or no entries yet)
        if ui_ready and (not entries or all(isinstance(e, RunningServerEntry) for e in entries.values())):
            lifecycle = AgentLifecycle.READY

    # Last activity timestamp (persisted)
    last_map = await persistence.list_agents_last_activity()
    last_at = last_map.get(agent_id)

    # Container id via runtime container.info (only when not ephemeral)
    container_id: str | None = None
    if c and present and (c.runtime_ephemeral is False) and c.compositor_client is not None:
        info = await read_text_json_typed(c.compositor_client.session, RUNTIME_CONTAINER_INFO_URI, ContainerInfo)
        container_id = info.container_id
    container = ContainerState(present=present, id=container_id, ephemeral=(c.runtime_ephemeral if c else False))

    # Run phase from live signals; no exceptions expected in this path
    # Check policy gateway for in-flight tool calls (if container and gateway exist)
    has_inflight = bool(c and c._policy_gateway and c._policy_gateway.has_inflight_calls())
    run_phase = determine_run_phase(pending_approvals=pending, mcp_has_inflight=has_inflight)

    return AgentStatusCore(
        id=agent_id,
        live=present and lifecycle in (AgentLifecycle.STARTING, AgentLifecycle.READY),
        lifecycle=lifecycle,
        run_phase=run_phase,
        ui=UiStateLite(ready=ui_ready),
        container=container,
        last_event_at=last_at,
    )
