from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ApprovalDecision(StrEnum):
    """Policy decision outcomes as string-valued enum.

    Use these values for all policy paths (in-proc and container) to keep
    decisions consistent and type-safe.
    """

    ALLOW = "allow"
    ASK = "ask"
    DENY_CONTINUE = "deny_continue"
    DENY_ABORT = "deny_abort"


class PolicyRequest(BaseModel):
    """Input to approval policy evaluation: tool name + JSON arguments.

    Note: Uses BaseModel not OpenAIStrictModeBaseModel because the arguments field
    is a free-form dict that varies by tool. This tool is for internal policy evaluation,
    not exposed directly to OpenAI API.

    TODO: Consider changing arguments to str (JSON-encoded) to enable OpenAI strict mode
    compatibility if this tool ever needs to be exposed directly to LLMs.
    """

    name: str
    arguments: dict[str, Any]
    model_config = ConfigDict(extra="forbid")


class PolicyResponse(BaseModel):
    """Structured decision result for approval evaluations."""

    decision: ApprovalDecision
    rationale: str


# Internal package: avoid public barrels; import explicitly where needed
