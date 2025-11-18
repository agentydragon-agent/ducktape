"""Hook outcome types - re-exported from parent package for convenience."""

from ...claude_outcomes import (
    HookError,
    HookOutcome,
    NotificationAcknowledge,
    PostToolNotifyLLM,
    PostToolSuccess,
    PreToolApprove,
    PreToolDeny,
    StopAllow,
    StopPrevent,
    SubagentStopAllow,
)

# Define missing outcome types that validation.py expects but don't exist yet
# These are likely legacy or planned types - for now, alias to existing types
PostToolSuccessWithInfo = PostToolSuccess
StopAllowWithInfo = StopAllow

__all__ = [
    "HookError",
    "HookOutcome",
    "NotificationAcknowledge",
    "PostToolNotifyLLM",
    "PostToolSuccess",
    "PostToolSuccessWithInfo",
    "PreToolApprove",
    "PreToolDeny",
    "StopAllow",
    "StopAllowWithInfo",
    "StopPrevent",
    "SubagentStopAllow",
]
