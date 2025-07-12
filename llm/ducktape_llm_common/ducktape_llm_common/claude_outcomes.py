"""User-friendly outcome types for Claude Code hooks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Union

from .claude_code_api import BaseResponse, PostToolResponse, PreToolResponse, StopResponse


# Outcome types - more user-friendly representations
@dataclass
class HookOutcome(ABC):
    """Base class for hook outcomes."""

    @abstractmethod
    def to_claude_response(self) -> BaseResponse:
        """Convert to Claude's expected response model."""
        pass


# PreToolUse Outcomes
@dataclass
class PreToolApprove(HookOutcome):
    """Allow tool execution (default behavior)."""

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse()  # defaults to approve


@dataclass
class PreToolDeny(HookOutcome):
    """
    Deny tool execution with message for Claude.

    Example:
        PreToolDeny(
            llm_message="Permission denied: Cannot edit production files. "
                       "To override, ask user to run: cl2 session allow 'Edit(\"prod/**\")'"
        )
    """

    llm_message: str

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse(decision="block", reason=self.llm_message)


PreToolOutcome = Union[PreToolApprove, PreToolDeny]


# PostToolUse Outcomes
@dataclass
class PostToolSuccess(HookOutcome):
    """Tool succeeded, no message needed."""

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse()


@dataclass
class PostToolNotifyLLM(HookOutcome):
    """
    Tool succeeded but Claude needs important feedback.

    Uses decision=block to ensure Claude processes the message.

    Example:
        PostToolNotifyLLM(
            llm_message="FYI: Applied autofix to your code:\n"
                       "- Formatted with black\n"
                       "- Added missing imports"
        )
    """

    llm_message: str

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse(decision="block", reason=self.llm_message)


PostToolOutcome = Union[PostToolSuccess, PostToolNotifyLLM]


# Stop Hook Outcomes
@dataclass
class StopAllow(HookOutcome):
    """Allow Claude to end its turn normally."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse()  # No decision = allow stop


@dataclass
class StopPrevent(HookOutcome):
    """
    Prevent Claude from ending its turn.

    Must provide reason for Claude to understand what to do.

    Example:
        StopPrevent(
            llm_message="Cannot end turn: 3 errors remain unfixed:\n"
                       "- Line 45: Bare except clause\n"
                       "Please fix these before ending."
        )
    """

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse(decision="block", reason=self.llm_message)


@dataclass
class StopAllowWithInfo(HookOutcome):
    """
    Allow stop but show info to Claude.

    Note: Per Anthropic docs, there's no user-only message in Stop hooks.
    This shows a message to Claude without blocking.

    Example:
        StopAllowWithInfo(
            llm_message="Note: 2 warnings remain. Consider fixing for better quality."
        )
    """

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        # No decision=block, just reason shows info without preventing stop
        return StopResponse(reason=self.llm_message)


StopOutcome = Union[StopAllow, StopPrevent, StopAllowWithInfo]


# SubagentStop Hook Outcomes
@dataclass
class SubagentStopAllow(HookOutcome):
    """Allow subagent to stop."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse()


SubagentStopOutcome = SubagentStopAllow


# Notification Hook Outcomes
@dataclass
class NotificationAcknowledge(HookOutcome):
    """Acknowledge notification."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse()


NotificationOutcome = NotificationAcknowledge


# PreCompact Hook Outcomes
@dataclass
class PreCompactAllow(HookOutcome):
    """Allow compaction to proceed."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse()


PreCompactOutcome = PreCompactAllow


# Error Outcome
@dataclass
class HookError(HookOutcome):
    """
    Hook processing error - stop Claude.

    This is the only outcome that sets continue=False to halt Claude.
    """

    error_message: str

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse(continue_=False, stopReason=f"Hook error: {self.error_message}")