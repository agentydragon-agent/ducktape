from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

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


def derive_run_phase(*, active_run_id: UUID | None, pending_approvals: int) -> RunPhase:
    """Coarse run phase derivation used by HTTP and WS status.

    - idle: no active run
    - waiting_approval: active run with pending approvals
    - sampling: active run without pending approvals (default)
    """
    if active_run_id is None:
        return RunPhase.IDLE
    if pending_approvals > 0:
        return RunPhase.WAITING_APPROVAL
    return RunPhase.SAMPLING


def determine_run_phase(
    *, active_run_id: UUID | None, pending_approvals: int, mcp_has_inflight: bool
) -> RunPhase:
    """Precise run phase from live signals.

    - IDLE: no active run
    - WAITING_APPROVAL: approvals pending
    - TOOLS_RUNNING: MCP manager has in-flight requests
    - SAMPLING: otherwise
    """
    if active_run_id is None:
        return RunPhase.IDLE
    if pending_approvals > 0:
        return RunPhase.WAITING_APPROVAL
    if mcp_has_inflight:
        return RunPhase.TOOLS_RUNNING
    return RunPhase.SAMPLING


class AgentLifecycle(StrEnum):
    PERSISTED_ONLY = "persisted_only"
    STARTING = "starting"
    READY = "ready"


"""Status models and builder (no host volumes reported)."""


class PolicyState(BaseModel):
    version: int | None = None
    model_config = ConfigDict(extra="forbid")


class UiStateLite(BaseModel):
    ready: bool
    model_config = ConfigDict(extra="forbid")


class McpState(BaseModel):
    entries: dict[str, ServerEntry]
    model_config = ConfigDict(extra="forbid")


class ContainerState(BaseModel):
    present: bool
    id: str | None
    ephemeral: bool
    model_config = ConfigDict(extra="forbid")


class AgentStatusCore(BaseModel):
    id: str
    live: bool
    active_run_id: UUID | None
    lifecycle: AgentLifecycle
    run_phase: RunPhase
    policy: PolicyState
    ui: UiStateLite
    mcp: McpState
    container: ContainerState
    pending_approvals: int
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

    # UI + approvals + active run
    ui_ready = bool(c and c.ui is not None)
    pending = 0
    active_run: UUID | None = None
    if c and c.session is not None:
        if c.session.active_run:
            active_run = c.session.active_run.run_id
        pending = len(c.session.approval_hub.pending)

    # Policy state from live engine only (single source of truth). If agent is not live, report absent.
    version_val: int | None = None
    if c and c.session is not None and c.session.approval_engine is not None:
        _content, ver = c.session.approval_engine.get_policy()
        version_val = ver
    policy = PolicyState(version=version_val)

    # MCP server entries — read via compositor_meta resources through container
    entries: dict[str, ServerEntry] = {}
    if c:
        entries = await c.list_mcp_entries()
    mcp_state = McpState(entries=entries)

    # Lifecycle
    if not present:
        lifecycle = AgentLifecycle.PERSISTED_ONLY
    else:
        lifecycle = AgentLifecycle.STARTING
        # READY when UI ready and all running (or no entries yet)
        if ui_ready and (
            not entries or all(isinstance(e, RunningServerEntry) for e in entries.values())
        ):
            lifecycle = AgentLifecycle.READY

    # Last activity timestamp (persisted)
    last_map = await persistence.list_agents_last_activity()
    last_at = last_map.get(agent_id)

    # Container id via runtime container.info (only when not ephemeral)
    container_id: str | None = None
    if c and present and (c.runtime_ephemeral is False) and c.mcp_client is not None:
        info = await read_text_json_typed(
            c.mcp_client.session, RUNTIME_CONTAINER_INFO_URI, ContainerInfo
        )
        container_id = info.container_id
    container = ContainerState(
        present=present, id=container_id, ephemeral=(c.runtime_ephemeral if c else False)
    )

    # Run phase from live signals; no exceptions expected in this path
    # Tool inflight detection is not exposed here; default to False
    has_inflight = False
    run_phase = determine_run_phase(
        active_run_id=active_run, pending_approvals=pending, mcp_has_inflight=has_inflight
    )

    return AgentStatusCore(
        id=agent_id,
        live=present and lifecycle in (AgentLifecycle.STARTING, AgentLifecycle.READY),
        active_run_id=active_run,
        lifecycle=lifecycle,
        run_phase=run_phase,
        policy=policy,
        ui=UiStateLite(ready=ui_ready),
        mcp=mcp_state,
        container=container,
        pending_approvals=pending,
        last_event_at=last_at,
    )
