"""User-friendly outcome types for Claude Code hooks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .claude_code_api import BaseResponse, PostToolResponse, PreToolResponse, StopResponse


# Outcome types - more user-friendly representations
@dataclass
class HookOutcome(ABC):
    """Base class for hook outcomes."""

    @abstractmethod
    def to_claude_response(self) -> BaseResponse:
        """Convert to Claude's expected response model."""


# PreToolUse Outcomes
@dataclass
class PreToolApprove(HookOutcome):
    """Explicitly approve tool execution, bypassing permission system."""

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse(decision="approve")


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


@dataclass
class PreToolNoOpinion(HookOutcome):
    """No opinion - let existing permission flow decide."""

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse()  # undefined decision = existing permission flow


PreToolOutcome = PreToolApprove | PreToolDeny | PreToolNoOpinion


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


@dataclass
class PostToolSuccessWithInfo(HookOutcome):
    """Tool succeeded with optional info (not blocking)."""

    info_message: str = ""

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse()


PostToolOutcome = PostToolSuccess | PostToolSuccessWithInfo | PostToolNotifyLLM


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
    """Allow Claude to end its turn, with an info message (non-blocking)."""

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse()


StopOutcome = StopAllow | StopAllowWithInfo | StopPrevent


# SubagentStop Hook Outcomes
@dataclass
class SubagentStopAllow(HookOutcome):
    """Allow subagent to stop."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse()


@dataclass
class SubagentStopPrevent(HookOutcome):
    """
    Prevent subagent from stopping.

    Must provide reason for the subagent to understand how to proceed.

    Example:
        SubagentStopPrevent(
            llm_message="Cannot stop: Must complete remaining analysis tasks."
        )
    """

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse(decision="block", reason=self.llm_message)


SubagentStopOutcome = SubagentStopAllow | SubagentStopPrevent


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
