from __future__ import annotations

from enum import StrEnum
from importlib import resources

from pydantic import BaseModel


class ApprovalToolCall(BaseModel):
    name: str
    call_id: str
    args_json: str | None = None


class ApprovalRequest(BaseModel):
    tool_key: str
    tool_call: ApprovalToolCall


class WellKnownTools(StrEnum):
    SEND_MESSAGE = "send_message"
    END_TURN = "end_turn"
    SANDBOX_EXEC = "sandbox_exec"  # adgn.mcp.seatbelt_exec.server


def load_default_policy_source() -> str:
    """Load the packaged default approval policy source code as text."""
    return resources.files("adgn.agent.policies").joinpath("default_policy.py").read_text(encoding="utf-8")
