"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system.
"""

from devinfra.claude.claude_api.hooks.pre_tool_use import (
    PermissionDecision,
    PreToolUseDecision,
    PreToolUseInput,
    PreToolUseOutput,
)
from devinfra.claude.settings import HookSettings

# --- Config ---

ALWAYS_ALLOW_COMMANDS: set[str] = {"echo hello world"}

# Default output: no opinion, fall through to normal permission flow.
_DEFAULT = PreToolUseOutput(
    hook_specific_output=PreToolUseDecision(
        permission_decision=PermissionDecision.ALLOW, permission_decision_reason="No policy matched"
    )
)


def evaluate(hook_input: PreToolUseInput, settings: HookSettings) -> PreToolUseOutput:
    """Evaluate a tool call against permission policies."""
    if hook_input.tool_name == "Bash":
        command = hook_input.tool_input.get("command", "")
        if command in ALWAYS_ALLOW_COMMANDS:
            return PreToolUseOutput(
                hook_specific_output=PreToolUseDecision(
                    permission_decision=PermissionDecision.ALLOW,
                    permission_decision_reason="Command in always-allow list",
                )
            )
    return _DEFAULT
