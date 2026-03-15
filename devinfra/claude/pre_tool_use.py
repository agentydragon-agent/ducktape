"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system. Returns no output to fall through to normal flow.
"""

from __future__ import annotations

from devinfra.claude.claude_api.pre_tool_use import (
    PermissionDecision,
    PreToolUseDecision,
    PreToolUseInput,
    PreToolUseOutput,
)

# --- Config ---

ALWAYS_ALLOW_COMMANDS: set[str] = {"echo hello world"}


def evaluate(hook_input: PreToolUseInput) -> PreToolUseOutput | None:
    """Evaluate a tool call. Returns output to override permissions, None to fall through."""
    if hook_input.tool_name == "Bash":
        command = hook_input.tool_input.get("command", "")
        if command in ALWAYS_ALLOW_COMMANDS:
            return PreToolUseOutput(
                hook_specific_output=PreToolUseDecision(
                    permission_decision=PermissionDecision.ALLOW,
                    permission_decision_reason="Command in always-allow list",
                )
            )
    return None
