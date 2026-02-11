from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from fastmcp.mcp_config import MCPConfig
from pydantic import BaseModel, ConfigDict, JsonValue


class AgentMetadata(BaseModel):
    """Typed per-agent metadata stored in persistence.

    Currently only preset name is tracked; expand here if new metadata is added.
    """

    preset: str


class AgentRow(BaseModel):
    id: str
    created_at: datetime
    mcp_config: MCPConfig
    metadata: AgentMetadata
    model_config = ConfigDict(arbitrary_types_allowed=True)


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    ABORTED = "aborted"


class ApprovalOutcome(StrEnum):
    POLICY_ALLOW = "policy_allow"
    POLICY_DENY_CONTINUE = "policy_deny_continue"
    POLICY_DENY_ABORT = "policy_deny_abort"
    USER_APPROVE = "user_approve"
    USER_DENY_CONTINUE = "user_deny_continue"
    USER_DENY_ABORT = "user_deny_abort"


class EventType(StrEnum):
    USER_TEXT = "user_text"
    ASSISTANT_TEXT = "assistant_text"
    TOOL_CALL = "tool_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"
    REASONING = "reasoning"
    RESPONSE = "response"


class RunRow(BaseModel):
    id: UUID
    agent_id: str | None
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    system_message: str | None
    model: str | None
    model_params: dict[str, JsonValue] | None
    event_count: int
    model_config = ConfigDict(arbitrary_types_allowed=True)


class PolicyProposal(BaseModel):
    id: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    content: str


from .events import EventRecord  # noqa: E402


class Persistence(Protocol):
    async def ensure_schema(self) -> None: ...

    # Agents API ---------------------------------------------------------------
    async def create_agent(self, *, mcp_config: MCPConfig, metadata: AgentMetadata) -> str: ...
    async def update_agent_specs(self, agent_id: str, *, mcp_config: MCPConfig) -> None: ...
    async def patch_agent_specs(
        self, agent_id: str, *, attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
    ) -> MCPConfig: ...
    async def list_agents(self) -> list[AgentRow]: ...
    async def get_agent(self, agent_id: str) -> AgentRow | None: ...
    async def list_agents_last_activity(self) -> dict[str, datetime | None]: ...
    async def delete_agent(self, agent_id: str) -> None: ...

    # Runs API -----------------------------------------------------------------
    async def start_run(
        self,
        *,
        run_id: UUID,
        agent_id: str | None,
        system_message: str | None,
        model: str | None,
        model_params: dict[str, JsonValue] | None,
        started_at: datetime,
    ) -> None: ...

    async def finish_run(self, run_id: UUID, *, status: RunStatus, finished_at: datetime) -> None: ...

    async def append_event(
        self,
        *,
        run_id: UUID,
        seq: int,
        ts: datetime,
        payload: dict[str, JsonValue],
        call_id: str | None = None,
        tool_key: str | None = None,
    ) -> None: ...

    async def record_approval(
        self,
        *,
        run_id: UUID,
        agent_id: str | None,
        call_id: str,
        tool_key: str,
        outcome: ApprovalOutcome,
        decided_at: datetime,
        details: dict[str, JsonValue] | None = None,
    ) -> None: ...

    async def list_runs(self, *, agent_id: str | None = None, limit: int = 50) -> list[RunRow]: ...
    async def get_run(self, run_id: UUID) -> RunRow | None: ...
    async def load_events(self, run_id: UUID) -> list[EventRecord]: ...

    # Approval policy (per-agent) --------------------------------------------
    async def get_latest_policy(self, agent_id: str) -> tuple[str, int] | None: ...
    async def set_policy(self, agent_id: str, *, content: str) -> int: ...

    # Approval policy proposals (single store impl: SQLite)
    async def create_policy_proposal(self, agent_id: str, *, proposal_id: str, content: str) -> None: ...
    async def list_policy_proposals(self, agent_id: str) -> list[PolicyProposal]: ...
    async def get_policy_proposal(self, agent_id: str, proposal_id: str) -> PolicyProposal | None: ...
    async def approve_policy_proposal(self, agent_id: str, proposal_id: str) -> int: ...
    async def reject_policy_proposal(self, agent_id: str, proposal_id: str) -> None: ...
    async def delete_policy_proposal(self, agent_id: str, proposal_id: str) -> None: ...
