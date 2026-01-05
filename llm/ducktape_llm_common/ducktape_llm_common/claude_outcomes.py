"""User-friendly outcome types for Claude Code hooks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .claude_code_api import BaseResponse, HookDecision, PostToolResponse, PreToolResponse, StopResponse


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
        return PreToolResponse(continue_=True, decision=HookDecision.APPROVE)


@dataclass
class PreToolDeny(HookOutcome):
    """Deny tool execution with message for Claude.

    Example: PreToolDeny(llm_message="Cannot edit production files")
    """

    llm_message: str

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse(continue_=True, decision=HookDecision.BLOCK, reason=self.llm_message)


@dataclass
class PreToolNoOpinion(HookOutcome):
    """No opinion - let existing permission flow decide."""

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse(continue_=True)  # undefined decision = existing permission flow


PreToolOutcome = PreToolApprove | PreToolDeny | PreToolNoOpinion


# PostToolUse Outcomes
@dataclass
class PostToolSuccess(HookOutcome):
    """Tool succeeded, no message needed."""

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse(continue_=True)


@dataclass
class PostToolNotifyLLM(HookOutcome):
    """Tool succeeded but Claude needs important feedback. Uses decision=block.

    Example: PostToolNotifyLLM(llm_message="Applied autofix: formatted with black")
    """

    llm_message: str

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse(continue_=True, decision=HookDecision.BLOCK, reason=self.llm_message)


@dataclass
class PostToolSuccessWithInfo(HookOutcome):
    """Tool succeeded with optional info (not blocking)."""

    info_message: str = ""

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse(continue_=True)


PostToolOutcome = PostToolSuccess | PostToolSuccessWithInfo | PostToolNotifyLLM


# Stop Hook Outcomes
@dataclass
class StopAllow(HookOutcome):
    """Allow Claude to end its turn normally."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse(continue_=True)  # No decision = allow stop


@dataclass
class StopPrevent(HookOutcome):
    """Prevent Claude from ending its turn.

    Example: StopPrevent(llm_message="Fix 3 remaining errors before ending")
    """

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse(continue_=True, decision=HookDecision.BLOCK, reason=self.llm_message)


@dataclass
class StopAllowWithInfo(HookOutcome):
    """Allow Claude to end its turn, with an info message (non-blocking)."""

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse(continue_=True)


StopOutcome = StopAllow | StopAllowWithInfo | StopPrevent


# SubagentStop Hook Outcomes
@dataclass
class SubagentStopAllow(HookOutcome):
    """Allow subagent to stop."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse(continue_=True)


@dataclass
class SubagentStopPrevent(HookOutcome):
    """
    Prevent subagent from stopping.

    Must provide reason for the subagent to understand how to proceed.

    Example:
        SubagentStopPrevent(llm_message="Cannot stop: Must complete remaining tasks.")
    """

    llm_message: str

    def to_claude_response(self) -> StopResponse:
        return StopResponse(continue_=True, decision=HookDecision.BLOCK, reason=self.llm_message)


SubagentStopOutcome = SubagentStopAllow | SubagentStopPrevent


# Notification Hook Outcomes
@dataclass
class NotificationAcknowledge(HookOutcome):
    """Acknowledge notification."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse(continue_=True)


NotificationOutcome = NotificationAcknowledge


# PreCompact Hook Outcomes
@dataclass
class PreCompactAllow(HookOutcome):
    """Allow compaction to proceed."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse(continue_=True)


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
        return BaseResponse(continue_=False, stop_reason=f"Hook error: {self.error_message}")
