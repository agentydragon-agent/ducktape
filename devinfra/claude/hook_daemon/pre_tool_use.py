"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system.
"""

from devinfra.claude.claude_api.hooks.pre_tool_use import (
    PermissionDecision,
    PreToolUseHookSpecificOutput,
    PreToolUseInput,
    PreToolUseOutput,
)
from devinfra.claude.hook_daemon.session import Session

# --- Config ---

ALWAYS_ALLOW_COMMANDS: frozenset[str] = frozenset({"echo hello world"})


def evaluate(hook_input: PreToolUseInput, session: Session) -> PreToolUseOutput:
    """Evaluate a tool call against permission policies."""
    system_message = session.take_precommit_status()

    if hook_input.tool_name == "Bash":
        command = hook_input.tool_input.get("command", "")
        if command in ALWAYS_ALLOW_COMMANDS:
            return PreToolUseOutput(
                system_message=system_message,
                hook_specific_output=PreToolUseHookSpecificOutput(
                    permission_decision=PermissionDecision.ALLOW,
                    permission_decision_reason="Command in always-allow list",
                ),
            )
    return PreToolUseOutput(system_message=system_message)
