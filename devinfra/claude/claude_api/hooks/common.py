"""Shared base classes and enums for Claude Code hook models.

Semantics Reference (from upstream Claude Code source)
======================================================

REPL vs non-REPL hooks
----------------------
Hooks are split into two execution paths:

**REPL hooks** (PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit,
Notification, Stop, SubagentStart, SubagentStop, PreCompact, PostCompact,
PermissionRequest, PermissionDenied, Elicitation, ElicitationResult):
  - ``systemMessage`` is injected into the model conversation as a
    ``hook_system_message`` attachment — **the model reads it**.
  - ``additionalContext`` (via ``hookSpecificOutput``) is also injected as a
    ``hook_additional_context`` attachment.

**Non-REPL hooks** (SessionStart, SessionEnd, Setup, CwdChanged, FileChanged,
InstructionsLoaded, WorktreeCreate, WorktreeRemove, ConfigChange):
  - ``systemMessage`` is delivered to the **UI notification callback only** —
    the model never sees it. This is a common footgun.
  - For SessionStart, use ``initialUserMessage`` or ``additionalContext`` via
    ``hookSpecificOutput`` to inject text that the model reads.

Exit code 2 = blocking
-----------------------
For shell command hooks, exit code 2 triggers blocking behavior equivalent to
``{"decision": "block"}``. This is distinct from JSON-based blocking.

SessionEnd timeout
------------------
SessionEnd hooks default to **1.5 seconds** (not the 10-minute default).
Override via ``CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`` env var.

CLAUDE_ENV_FILE availability
-----------------------------
Only these hooks receive ``CLAUDE_ENV_FILE`` in their environment (allowing
hooks to inject env vars into the bash shell):
  - SessionStart, Setup, CwdChanged, FileChanged

PreToolUse permission semantics
-------------------------------
- ``permissionDecision: 'allow'`` does **NOT** bypass settings.json deny/ask
  rules. ``checkRuleBasedPermissions()`` still runs after the hook. If a deny
  rule matches, deny wins. If an ask rule matches, the user still gets prompted.
- When multiple hooks run: **deny > ask > allow** precedence.
- ``updatedInput`` without a ``permissionDecision`` still modifies the tool
  input (passthrough path) while the normal permission flow applies.
- ``updatedInput`` is only honored with ``allow`` or ``ask``; silently dropped
  with ``deny`` (tool won't run anyway).
- ``updatedInput`` + ``allow`` satisfies ``requiresUserInteraction`` for tools
  like AskUserQuestion — the hook IS the user interaction.

PostToolUse caveats
-------------------
- ``updatedMCPToolOutput`` is silently ignored for non-MCP tools (checked via
  ``isMcpTool()`` upstream).

Workspace trust
---------------
All hooks require workspace trust in interactive mode. If the trust dialog
hasn't been accepted, ALL hooks are skipped.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class PermissionMode(StrEnum):
    """Claude Code permission mode values."""

    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    DONT_ASK = "dontAsk"
    AUTO = "auto"


class CamelModel(BaseModel):
    """Base for hook output models — serializes fields as camelCase, rejects extra fields."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class HookInputBase(BaseModel):
    """Common fields present in all hook inputs."""

    session_id: str
    transcript_path: Path
    cwd: Path
    permission_mode: PermissionMode | None = Field(
        default=None, description="Not sent by Claude Code Web for some SessionStart events"
    )
    agent_id: str | None = Field(
        default=None, description="Subagent identifier. Present only when the hook fires from within a subagent."
    )
    parent_session_id: str | None = Field(default=None, description="Parent session ID when running as a subagent.")
    agent_type: str | None = Field(
        default=None,
        description="Agent type name. Present in subagent context (with agent_id) or on main thread with --agent.",
    )
