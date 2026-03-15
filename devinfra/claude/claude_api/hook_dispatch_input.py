"""Discriminated union of all Claude Code hook inputs.

Parsed once in hook_dispatch.py, then isinstance/match dispatches to the
appropriate handler. Uses hook_event_name as the Pydantic discriminator.
"""

from typing import Annotated

from pydantic import Discriminator

from devinfra.claude.claude_api.hooks import (
    ConfigChangeInput,
    ElicitationInput,
    ElicitationResultInput,
    InstructionsLoadedInput,
    NotificationInput,
    PermissionRequestInput,
    PostCompactInput,
    PostToolUseFailureInput,
    PreCompactInput,
    SessionEndInput,
    StopInput,
    SubagentStartInput,
    SubagentStopInput,
    TaskCompletedInput,
    TeammateIdleInput,
    UserPromptSubmitInput,
    WorktreeCreateInput,
    WorktreeRemoveInput,
)
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.session_start_input import SessionStartHookInput

AnyHookInput = Annotated[
    SessionStartHookInput
    | PreToolUseInput
    | PostToolUseInput
    | UserPromptSubmitInput
    | NotificationInput
    | StopInput
    | SubagentStartInput
    | SubagentStopInput
    | PostToolUseFailureInput
    | PermissionRequestInput
    | ElicitationInput
    | ElicitationResultInput
    | ConfigChangeInput
    | PreCompactInput
    | PostCompactInput
    | InstructionsLoadedInput
    | WorktreeCreateInput
    | WorktreeRemoveInput
    | SessionEndInput
    | TeammateIdleInput
    | TaskCompletedInput,
    Discriminator("hook_event_name"),
]
