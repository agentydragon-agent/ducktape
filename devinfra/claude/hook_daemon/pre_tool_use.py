"""PreToolUse hook: programmatic permission predicate.

Evaluates tool calls and returns allow/deny/ask decisions before Claude Code's
normal permission system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from devinfra.claude.claude_api.hooks.output import HookOutput
from devinfra.claude.claude_api.hooks.pre_tool_use import (
    PermissionDecision,
    PreToolUseHookSpecificOutput,
    PreToolUseInput,
)
from devinfra.claude.claude_api.tool_input_models import BashInput
from devinfra.claude.hook_daemon.tool_input_parsing import parse_tool_input

if TYPE_CHECKING:
    from devinfra.claude.hook_daemon.session import Session

logger = logging.getLogger(__name__)

# --- Config ---

ALWAYS_ALLOW_COMMANDS: frozenset[str] = frozenset({"echo hello world"})


def evaluate(hook_input: PreToolUseInput, session: Session) -> HookOutput:
    """Evaluate a tool call against permission policies."""
    try:
        parsed = parse_tool_input(hook_input.tool_name, hook_input.tool_input)
    except ValidationError as e:
        msg = f"Failed to parse {hook_input.tool_name} tool_input: {e}"
        logger.warning(msg)
        session.post_message(f"[tool_input_parsing] {msg}")
        return HookOutput()

    if isinstance(parsed, BashInput) and parsed.command in ALWAYS_ALLOW_COMMANDS:
        return HookOutput(
            hook_specific_output=PreToolUseHookSpecificOutput(
                permission_decision=PermissionDecision.ALLOW, permission_decision_reason="Command in always-allow list"
            )
        )

    return HookOutput()
