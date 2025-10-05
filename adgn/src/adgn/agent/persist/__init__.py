from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class AgentRow(BaseModel):
    id: str
    created_at: datetime
    specs: dict[str, Any]
    metadata: dict[str, Any] | None = None
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
    id: str
    agent_id: str | None
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    system_message: str | None
    model: str | None
    model_params: dict[str, Any] | None
    event_count: int
    model_config = ConfigDict(arbitrary_types_allowed=True)


from .events import EventRecord  # noqa: E402


class Persistence(Protocol):
    async def ensure_schema(self) -> None: ...

    # Agents API ---------------------------------------------------------------
    async def create_agent(
        self, *, specs: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> str: ...
    async def update_agent_specs(self, agent_id: str, *, specs: dict[str, Any]) -> None: ...
    async def patch_agent_specs(
        self,
        agent_id: str,
        *,
        attach: dict[str, Any] | None = None,
        detach: list[str] | None = None,
    ) -> dict[str, Any]: ...
    async def list_agents(self) -> list[AgentRow]: ...
    async def get_agent(self, agent_id: str) -> AgentRow | None: ...
    async def list_agents_last_activity(self) -> dict[str, datetime | None]: ...
    async def delete_agent(self, agent_id: str) -> None: ...

    # Runs API -----------------------------------------------------------------
    async def start_run(
        self,
        *,
        run_id: str,
        agent_id: str | None,
        system_message: str | None,
        model: str | None,
        model_params: dict[str, Any] | None,
        started_at: datetime,
    ) -> None: ...

    async def finish_run(
        self, run_id: str, *, status: RunStatus, finished_at: datetime
    ) -> None: ...

    async def append_event(
        self,
        *,
        run_id: str,
        seq: int,
        ts: datetime,
        type: EventType,
        payload: dict[str, Any],
        call_id: str | None = None,
        tool_key: str | None = None,
    ) -> None: ...

    async def record_approval(
        self,
        *,
        run_id: str,
        agent_id: str | None,
        call_id: str,
        tool_key: str,
        outcome: ApprovalOutcome,
        decided_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    async def list_runs(self, *, agent_id: str | None = None, limit: int = 50) -> list[RunRow]: ...
    async def get_run(self, run_id: str) -> RunRow | None: ...
    async def load_events(self, run_id: str) -> list[EventRecord]: ...

    # Approval policy (per-agent) --------------------------------------------
    async def get_latest_policy(self, agent_id: str) -> tuple[str, int] | None: ...
    async def set_policy(self, agent_id: str, *, content: str) -> int: ...
    async def create_proposal(
        self,
        agent_id: str,
        *,
        proposal_id: str,
        source: str,
        rationale: str | None,
        created_at: datetime,
    ) -> None: ...
    async def set_proposal_status(
        self,
        agent_id: str,
        *,
        proposal_id: str,
        status: str,
        decided_at: datetime | None,
    ) -> None: ...
    async def list_proposals(self, agent_id: str) -> list[dict[str, Any]]: ...
