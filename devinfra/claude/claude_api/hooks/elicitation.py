"""Pydantic models for Claude Code Elicitation and ElicitationResult hooks."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class ElicitationAction(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"


class ElicitationMode(StrEnum):
    FORM = "form"
    URL = "url"


class ElicitationInput(HookInputBase):
    hook_event_name: Literal["Elicitation"] = "Elicitation"
    mcp_server_name: str = ""
    message: str = ""
    mode: ElicitationMode | None = None
    url: str | None = None
    requested_schema: dict[str, Any] | None = None


class ElicitationHookSpecificOutput(CamelModel):
    hook_event_name: Literal["Elicitation"] = "Elicitation"
    action: ElicitationAction
    content: dict[str, Any] | None = None


class ElicitationOutput(CamelModel):
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: ElicitationHookSpecificOutput | None = None


class ElicitationResultInput(HookInputBase):
    hook_event_name: Literal["ElicitationResult"] = "ElicitationResult"
    mcp_server_name: str = ""
    action: ElicitationAction | None = None
    content: dict[str, Any] | None = None
    mode: ElicitationMode | None = None
    elicitation_id: str = ""


class ElicitationResultHookSpecificOutput(CamelModel):
    hook_event_name: Literal["ElicitationResult"] = "ElicitationResult"
    action: ElicitationAction
    content: dict[str, Any] | None = None


class ElicitationResultOutput(CamelModel):
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: ElicitationResultHookSpecificOutput | None = None
