"""Hook request types - re-exported from parent package for convenience."""

from ...claude_code_api import (
    BaseHookRequest,
    NotificationRequest,
    PostToolUseRequest,
    PreToolUseRequest,
    StopRequest,
    SubagentStopRequest,
)

# Mapping of hook event names to request classes
HOOK_REQUEST_TYPES = {
    "PreToolUse": PreToolUseRequest,
    "PostToolUse": PostToolUseRequest,
    "Notification": NotificationRequest,
    "Stop": StopRequest,
    "SubagentStop": SubagentStopRequest,
}

__all__ = [
    "BaseHookRequest",
    "NotificationRequest",
    "PostToolUseRequest",
    "PreToolUseRequest",
    "StopRequest",
    "SubagentStopRequest",
    "HOOK_REQUEST_TYPES",
]
