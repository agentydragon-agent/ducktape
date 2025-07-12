"""Base class for Claude Code hooks with convenient entrypoint."""

import json
import sys
from abc import ABC, abstractmethod
from typing import Union

from .claude_code_api import (
    NotificationRequest,
    PostToolUseRequest,
    PreCompactRequest,
    PreToolUseRequest,
    StopRequest,
    SubagentStopRequest,
)
from .claude_outcomes import (
    HookError,
    HookOutcome,
    NotificationAcknowledge,
    NotificationOutcome,
    PostToolNotifyLLM,
    PostToolOutcome,
    PostToolSuccess,
    PreCompactAllow,
    PreCompactOutcome,
    PreToolApprove,
    PreToolDeny,
    PreToolOutcome,
    StopAllow,
    StopAllowWithInfo,
    StopOutcome,
    StopPrevent,
    SubagentStopAllow,
    SubagentStopOutcome,
)


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
