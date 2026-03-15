"""Pydantic models for all Claude Code hook types not handled by dedicated modules.

Dedicated modules exist for: SessionStart, PreToolUse, PostToolUse.
This module covers: UserPromptSubmit, Notification, Stop, SubagentStart, SubagentStop,
PostToolUseFailure, PermissionRequest, Elicitation, ElicitationResult, ConfigChange,
PreCompact, PostCompact, InstructionsLoaded, WorktreeCreate, WorktreeRemove,
SessionEnd, TeammateIdle, TaskCompleted.

See https://code.claude.com/docs/en/hooks for the full API spec.
"""

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from devinfra.claude.claude_api.permission_mode import PermissionMode


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── Enums ──


class NotificationType(StrEnum):
    PERMISSION_PROMPT = "permission_prompt"
    IDLE_PROMPT = "idle_prompt"
    AUTH_SUCCESS = "auth_success"
    ELICITATION_DIALOG = "elicitation_dialog"


class ElicitationAction(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"


class ElicitationMode(StrEnum):
    FORM = "form"
    URL = "url"


class ConfigChangeSource(StrEnum):
    USER_SETTINGS = "user_settings"
    PROJECT_SETTINGS = "project_settings"
    LOCAL_SETTINGS = "local_settings"
    POLICY_SETTINGS = "policy_settings"
    SKILLS = "skills"


class CompactTrigger(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class InstructionsMemoryType(StrEnum):
    USER = "User"
    PROJECT = "Project"
    LOCAL = "Local"
    MANAGED = "Managed"


class InstructionsLoadReason(StrEnum):
    SESSION_START = "session_start"
    NESTED_TRAVERSAL = "nested_traversal"
    PATH_GLOB_MATCH = "path_glob_match"
    INCLUDE = "include"


class SessionEndReason(StrEnum):
    CLEAR = "clear"
    LOGOUT = "logout"
    PROMPT_INPUT_EXIT = "prompt_input_exit"
    BYPASS_PERMISSIONS_DISABLED = "bypass_permissions_disabled"
    OTHER = "other"


# ── Input models ──


class _HookInputBase(BaseModel):
    """Common fields present in most hook inputs."""

    session_id: str
    transcript_path: Path
    cwd: Path
    permission_mode: PermissionMode


class UserPromptSubmitInput(_HookInputBase):
    hook_event_name: Literal["UserPromptSubmit"] = "UserPromptSubmit"
    prompt: str


class NotificationInput(_HookInputBase):
    hook_event_name: Literal["Notification"] = "Notification"
    message: str
    title: str = ""
    notification_type: NotificationType | None = None


class StopInput(_HookInputBase):
    hook_event_name: Literal["Stop"] = "Stop"
    stop_hook_active: bool = False
    last_assistant_message: str = ""


class SubagentStartInput(_HookInputBase):
    hook_event_name: Literal["SubagentStart"] = "SubagentStart"
    agent_id: str = ""
    agent_type: str = ""


class SubagentStopInput(_HookInputBase):
    hook_event_name: Literal["SubagentStop"] = "SubagentStop"
    stop_hook_active: bool = False
    agent_id: str = ""
    agent_type: str = ""
    agent_transcript_path: Path | None = None
    last_assistant_message: str = ""


class PostToolUseFailureInput(_HookInputBase):
    hook_event_name: Literal["PostToolUseFailure"] = "PostToolUseFailure"
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str = ""
    error: str = ""
    is_interrupt: bool = False


class PermissionSuggestion(BaseModel):
    type: str
    tool: str


class PermissionRequestInput(_HookInputBase):
    hook_event_name: Literal["PermissionRequest"] = "PermissionRequest"
    tool_name: str
    tool_input: dict[str, Any]
    permission_suggestions: list[PermissionSuggestion] = Field(default_factory=list)


class ElicitationInput(_HookInputBase):
    hook_event_name: Literal["Elicitation"] = "Elicitation"
    mcp_server_name: str = ""
    message: str = ""
    mode: ElicitationMode | None = None
    url: str | None = None
    requested_schema: dict[str, Any] | None = None


class ElicitationResultInput(_HookInputBase):
    hook_event_name: Literal["ElicitationResult"] = "ElicitationResult"
    mcp_server_name: str = ""
    action: ElicitationAction | None = None
    content: dict[str, Any] | None = None
    mode: ElicitationMode | None = None
    elicitation_id: str = ""


class ConfigChangeInput(_HookInputBase):
    hook_event_name: Literal["ConfigChange"] = "ConfigChange"
    source: ConfigChangeSource
    file_path: Path


class PreCompactInput(_HookInputBase):
    hook_event_name: Literal["PreCompact"] = "PreCompact"
    trigger: CompactTrigger
    custom_instructions: str = ""


class PostCompactInput(_HookInputBase):
    hook_event_name: Literal["PostCompact"] = "PostCompact"
    trigger: CompactTrigger
    compact_summary: str = ""


class InstructionsLoadedInput(_HookInputBase):
    hook_event_name: Literal["InstructionsLoaded"] = "InstructionsLoaded"
    file_path: Path
    memory_type: InstructionsMemoryType | None = None
    load_reason: InstructionsLoadReason | None = None
    globs: list[str] = Field(default_factory=list)
    trigger_file_path: Path | None = None
    parent_file_path: Path | None = None


class WorktreeCreateInput(BaseModel):
    """WorktreeCreate input (no permission_mode field)."""

    session_id: str
    transcript_path: Path
    cwd: Path
    hook_event_name: Literal["WorktreeCreate"] = "WorktreeCreate"
    name: str = ""


class WorktreeRemoveInput(BaseModel):
    """WorktreeRemove input (no permission_mode field)."""

    session_id: str
    transcript_path: Path
    cwd: Path
    hook_event_name: Literal["WorktreeRemove"] = "WorktreeRemove"
    worktree_path: Path


class SessionEndInput(_HookInputBase):
    hook_event_name: Literal["SessionEnd"] = "SessionEnd"
    reason: SessionEndReason | None = None


class TeammateIdleInput(_HookInputBase):
    hook_event_name: Literal["TeammateIdle"] = "TeammateIdle"
    teammate_name: str = ""
    team_name: str = ""


class TaskCompletedInput(_HookInputBase):
    hook_event_name: Literal["TaskCompleted"] = "TaskCompleted"
    task_id: str = ""
    task_subject: str = ""
    task_description: str = ""
    teammate_name: str = ""
    team_name: str = ""


# ── Output models ──


class UserPromptSubmitOutput(_CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to reject the prompt")
    reason: str | None = Field(default=None, description="Message shown to user when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: dict[str, Any] | None = Field(
        default=None, description="hookSpecificOutput with additionalContext"
    )


class StopOutput(_CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to prevent stopping")
    reason: str | None = Field(default=None, description="Feedback to Claude when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False


class SubagentStopOutput(_CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to keep subagent working")
    reason: str | None = Field(default=None, description="Feedback to subagent when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False


class PermissionRequestDecision(_CamelModel):
    behavior: Literal["allow", "deny"]
    updated_input: dict[str, Any] | None = None
    updated_permissions: list[Any] | None = None
    message: str | None = Field(default=None, description="Reason shown when behavior='deny'")


class PermissionRequestHookSpecificOutput(_CamelModel):
    hook_event_name: Literal["PermissionRequest"] = "PermissionRequest"
    decision: PermissionRequestDecision


class PermissionRequestOutput(_CamelModel):
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: PermissionRequestHookSpecificOutput | None = None


class ElicitationHookSpecificOutput(_CamelModel):
    hook_event_name: Literal["Elicitation"] = "Elicitation"
    action: ElicitationAction
    content: dict[str, Any] | None = None


class ElicitationOutput(_CamelModel):
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: ElicitationHookSpecificOutput | None = None


class ElicitationResultHookSpecificOutput(_CamelModel):
    hook_event_name: Literal["ElicitationResult"] = "ElicitationResult"
    action: ElicitationAction
    content: dict[str, Any] | None = None


class ElicitationResultOutput(_CamelModel):
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: ElicitationResultHookSpecificOutput | None = None


class ConfigChangeOutput(_CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to reject the config change")
    reason: str | None = None
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
