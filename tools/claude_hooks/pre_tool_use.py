"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system. Returns no output to fall through to normal flow.
"""

from __future__ import annotations

import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Input models ---


class PreToolUseInput(BaseModel):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: Literal["default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"]
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


# --- Output models ---


class PreToolUseDecision(_CamelModel):
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "deny", "ask"]
    permission_decision_reason: str


class PreToolUseOutput(_CamelModel):
    hook_specific_output: PreToolUseDecision


# --- Config ---

ALWAYS_ALLOW_COMMANDS: set[str] = {"echo hello world"}


def evaluate(hook_input: PreToolUseInput) -> PreToolUseOutput | None:
    """Evaluate a tool call. Returns output to override permissions, None to fall through."""
    if hook_input.tool_name == "Bash":
        command = hook_input.tool_input.get("command", "")
        if command in ALWAYS_ALLOW_COMMANDS:
            return PreToolUseOutput(
                hook_specific_output=PreToolUseDecision(
                    permission_decision="allow", permission_decision_reason="Command in always-allow list"
                )
            )
    return None


def main() -> None:
    hook_input = PreToolUseInput.model_validate_json(sys.stdin.read())
    result = evaluate(hook_input)
    if result is not None:
        sys.stdout.write(result.model_dump_json(by_alias=True))
