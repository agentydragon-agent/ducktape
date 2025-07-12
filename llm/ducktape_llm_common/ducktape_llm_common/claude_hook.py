"""Base class for Claude Code hooks with convenient entrypoint."""

import json
import sys
from abc import ABC, abstractmethod
from typing import Union

from .claude_code_api import (
    BaseResponse,
    NotificationRequest,
    PostToolResponse,
    PostToolUseRequest,
    PreCompactRequest,
    PreToolResponse,
    PreToolUseRequest,
    StopRequest,
    StopResponse,
    SubagentStopRequest,
)


# Outcome types - more user-friendly representations
class HookOutcome(ABC):
    """Base class for hook outcomes."""

    @abstractmethod
    def to_claude_response(self) -> BaseResponse:
        """Convert to Claude's expected response model."""
        pass


# PreToolUse Outcomes
class PreToolApprove(HookOutcome):
    """Allow tool execution (default behavior)."""

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse()  # defaults to approve


class PreToolDeny(HookOutcome):
    """
    Deny tool execution with message for Claude.

    Example:
        PreToolDeny(
            llm_message="Permission denied: Cannot edit production files. "
                       "To override, ask user to run: cl2 session allow 'Edit(\"prod/**\")'"
        )
    """

    def __init__(self, llm_message: str):
        self.llm_message = llm_message

    def to_claude_response(self) -> PreToolResponse:
        return PreToolResponse(decision="block", reason=self.llm_message)


PreToolOutcome = Union[PreToolApprove, PreToolDeny]


# PostToolUse Outcomes
class PostToolSuccess(HookOutcome):
    """Tool succeeded, no message needed."""

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse()


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

    def __init__(self, llm_message: str):
        self.llm_message = llm_message

    def to_claude_response(self) -> PostToolResponse:
        return PostToolResponse(decision="block", reason=self.llm_message)


PostToolOutcome = Union[PostToolSuccess, PostToolNotifyLLM]


# Stop Hook Outcomes
class StopAllow(HookOutcome):
    """Allow Claude to end its turn normally."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse()  # No decision = allow stop


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

    def __init__(self, llm_message: str):
        self.llm_message = llm_message

    def to_claude_response(self) -> StopResponse:
        return StopResponse(decision="block", reason=self.llm_message)


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

    def __init__(self, llm_message: str):
        self.llm_message = llm_message

    def to_claude_response(self) -> StopResponse:
        # No decision=block, just reason shows info without preventing stop
        return StopResponse(reason=self.llm_message)


StopOutcome = Union[StopAllow, StopPrevent, StopAllowWithInfo]


# SubagentStop Hook Outcomes
class SubagentStopAllow(HookOutcome):
    """Allow subagent to stop."""

    def to_claude_response(self) -> StopResponse:
        return StopResponse()


SubagentStopOutcome = SubagentStopAllow


# Notification Hook Outcomes
class NotificationAcknowledge(HookOutcome):
    """Acknowledge notification."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse()


NotificationOutcome = NotificationAcknowledge


# PreCompact Hook Outcomes
class PreCompactAllow(HookOutcome):
    """Allow compaction to proceed."""

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse()


PreCompactOutcome = PreCompactAllow


# Error Outcome
class HookError(HookOutcome):
    """
    Hook processing error - stop Claude.

    This is the only outcome that sets continue=False to halt Claude.
    """

    def __init__(self, error_message: str):
        self.error_message = error_message

    def to_claude_response(self) -> BaseResponse:
        return BaseResponse(continue_=False, stopReason=f"Hook error: {self.error_message}")


class ClaudeCodeHookBase(ABC):
    """
    Base class for implementing Claude Code hooks.
    
    Subclasses should implement the hook methods they want to handle.
    
    Example:
        class MyClaudeHook(ClaudeCodeHookBase):
            def pre_tool_use(self, request: PreToolUseRequest) -> PreToolOutcome:
                if request.tool_name == "Bash" and "rm -rf" in (request.tool_input.command or ""):
                    return PreToolDeny("Dangerous command blocked")
                return PreToolApprove()
                
            def post_tool_use(self, request: PostToolUseRequest) -> PostToolOutcome:
                return PostToolSuccess()
        
        if __name__ == '__main__':
            MyClaudeHook.entrypoint()
    """

    def pre_tool_use(self, request: PreToolUseRequest) -> PreToolOutcome:
        """Handle PreToolUse hook. Default: approve all tools."""
        return PreToolApprove()

    def post_tool_use(self, request: PostToolUseRequest) -> PostToolOutcome:
        """Handle PostToolUse hook. Default: success with no message."""
        return PostToolSuccess()

    def notification(self, request: NotificationRequest) -> NotificationOutcome:
        """Handle Notification hook. Default: acknowledge."""
        return NotificationAcknowledge()

    def stop(self, request: StopRequest) -> StopOutcome:
        """Handle Stop hook. Default: allow stop."""
        return StopAllow()

    def subagent_stop(self, request: SubagentStopRequest) -> SubagentStopOutcome:
        """Handle SubagentStop hook. Default: allow stop."""
        return SubagentStopAllow()

    def pre_compact(self, request: PreCompactRequest) -> PreCompactOutcome:
        """Handle PreCompact hook. Default: allow compaction."""
        return PreCompactAllow()

    @classmethod
    def entrypoint(cls) -> None:
        """
        Main entrypoint for Claude Code hooks.
        
        Reads JSON from stdin, dispatches to appropriate method, 
        returns JSON to stdout, exits with code 0.
        
        Usage:
            if __name__ == '__main__':
                MyClaudeHook.entrypoint()
        """
        try:
            # Read JSON from stdin
            input_data = json.load(sys.stdin)
            
            # Extract hook event name
            hook_event_name = input_data.get("hook_event_name", "")
            
            # Create instance
            hook_instance = cls()
            
            # Parse and dispatch based on hook type
            if hook_event_name == "PreToolUse":
                request = PreToolUseRequest.model_validate(input_data)
                outcome = hook_instance.pre_tool_use(request)
            elif hook_event_name == "PostToolUse":
                request = PostToolUseRequest.model_validate(input_data)
                outcome = hook_instance.post_tool_use(request)
            elif hook_event_name == "Notification":
                request = NotificationRequest.model_validate(input_data)
                outcome = hook_instance.notification(request)
            elif hook_event_name == "Stop":
                request = StopRequest.model_validate(input_data)
                outcome = hook_instance.stop(request)
            elif hook_event_name == "SubagentStop":
                request = SubagentStopRequest.model_validate(input_data)
                outcome = hook_instance.subagent_stop(request)
            elif hook_event_name == "PreCompact":
                request = PreCompactRequest.model_validate(input_data)
                outcome = hook_instance.pre_compact(request)
            else:
                # Unknown hook type
                outcome = HookError(f"Unknown hook type: {hook_event_name}")
            
            # Convert outcome to Claude response
            response = outcome.to_claude_response()
            
            # Output JSON response
            print(response.model_dump_json(by_alias=True))
            sys.exit(0)
            
        except Exception as e:
            # On any error, return error outcome
            error_outcome = HookError(f"Hook execution failed: {str(e)}")
            response = error_outcome.to_claude_response()
            print(response.model_dump_json(by_alias=True))
            sys.exit(0)
