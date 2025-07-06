"""Algebraic data types for hook outcomes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .claude_responses import ClaudeBaseResponse, ClaudePostToolResponse, ClaudePreToolResponse, ClaudeStopResponse


@dataclass
class HookOutcome(ABC):
    """Base class for hook outcomes."""

    @abstractmethod
    def to_claude_response(self) -> ClaudeBaseResponse:
        """Convert to Claude's expected response model."""
        pass


# ===== PreToolUse Outcomes =====
@dataclass
class PreToolApprove(HookOutcome):
    """Allow tool execution (default behavior)."""

    def to_claude_response(self) -> ClaudePreToolResponse:
        return ClaudePreToolResponse()  # defaults to approve


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

    llm_message: str  # Shown to Claude for retry guidance

    def to_claude_response(self) -> ClaudePreToolResponse:
        return ClaudePreToolResponse(decision="block", reason=self.llm_message)


PreToolOutcome = PreToolApprove | PreToolDeny


# ===== PostToolUse Outcomes =====
@dataclass
class PostToolSuccess(HookOutcome):
    """Tool succeeded, no message needed."""

    def to_claude_response(self) -> ClaudePostToolResponse:
        return ClaudePostToolResponse()


@dataclass
class PostToolSuccessWithInfo(HookOutcome):
    """Tool succeeded with informational message."""

    message: str

    def to_claude_response(self) -> ClaudePostToolResponse:
        return ClaudePostToolResponse(reason=self.message)


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

    def to_claude_response(self) -> ClaudePostToolResponse:
        return ClaudePostToolResponse(decision="block", reason=self.llm_message)


PostToolOutcome = PostToolSuccess | PostToolSuccessWithInfo | PostToolNotifyLLM


# ===== Stop Hook Outcomes =====
@dataclass
class StopAllow(HookOutcome):
    """Allow Claude to end its turn normally."""

    # No continue param - allowing stop means Claude decides

    def to_claude_response(self) -> ClaudeStopResponse:
        return ClaudeStopResponse()  # No decision = allow stop


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

    llm_message: str  # What Claude needs to do
    # No continue param - preventing stop implies continue=True

    def to_claude_response(self) -> ClaudeStopResponse:
        return ClaudeStopResponse(decision="block", reason=self.llm_message)


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
    # No continue param - allowing stop with info

    def to_claude_response(self) -> ClaudeStopResponse:
        # No decision=block, just reason shows info without preventing stop
        return ClaudeStopResponse(reason=self.llm_message)


StopOutcome = StopAllow | StopPrevent | StopAllowWithInfo


# ===== Other Hooks =====
@dataclass
class SubagentStopAllow(HookOutcome):
    """Allow subagent to stop."""

    def to_claude_response(self) -> ClaudeStopResponse:
        return ClaudeStopResponse()


@dataclass
class NotificationAcknowledge(HookOutcome):
    """Acknowledge notification."""

    def to_claude_response(self) -> ClaudeBaseResponse:
        return ClaudeBaseResponse()


# ===== Error Outcome (explicit continue=False) =====
@dataclass
class HookError(HookOutcome):
    """
    Hook processing error - stop Claude.

    This is the only outcome that sets continue=False to halt Claude.
    """

    error_message: str

    def to_claude_response(self) -> ClaudeBaseResponse:
        return ClaudeBaseResponse(continue_=False, stopReason=f"Hook error: {self.error_message}")
