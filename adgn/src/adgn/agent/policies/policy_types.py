from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ApprovalDecision(StrEnum):
    """Policy decision outcomes as string-valued enum.

    Use these values for all policy paths (in-proc and container) to keep
    decisions consistent and type-safe.
    """

    ALLOW = "allow"
    ASK = "ask"
    DENY_CONTINUE = "deny_continue"
    DENY_ABORT = "deny_abort"


class UserApprovalDecision(StrEnum):
    """User decision for approval requests (UI-facing).

    Distinct from policy evaluation decisions; these are the concrete
    approval responses submitted by the user to approve/deny tool calls.
    """

    APPROVE = "approve"
    DENY_CONTINUE = "deny_continue"
    DENY_ABORT = "deny_abort"


class PolicyRequest(BaseModel):
    """Input to approval policy evaluation: tool name + JSON arguments."""

    name: str
    arguments: dict[str, Any] | None = None


class PolicyResponse(BaseModel):
    """Structured decision result for approval evaluations."""

    decision: ApprovalDecision
    rationale: str


# Internal package: avoid public barrels; import explicitly where needed
