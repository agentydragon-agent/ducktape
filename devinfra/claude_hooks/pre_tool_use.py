"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system. Returns no output to fall through to normal flow.
"""

from __future__ import annotations

import sys

from devinfra.claude_hooks.claude_api.pre_tool_use import PreToolUseDecision, PreToolUseInput, PreToolUseOutput

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
