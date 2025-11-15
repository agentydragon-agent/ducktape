"""Pydantic models for Claude Code hook request/response structures.

These models represent the JSON data exchanged between Claude Code and hook commands.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HookResponse(BaseModel):
    """Response sent back to Claude Code from a hook command.

    Hook can communicate decisions via:
    1. Exit codes: 0=success, 2=blocking error, other=non-blocking error
    2. JSON output (this model) for fine-grained control

    When using JSON output, exit code should be 0.
    """

    decision: Literal["approve", "block"] | None = None
    """Controls tool execution (PreToolUse) or provides feedback (PostToolUse).
    - approve: Allow operation to proceed
    - block: Prevent operation (pre) or signal changes were made (post)
    """

    reason: str | None = None
    """Human-readable explanation shown to user and/or used to re-prompt model."""

    continue_: bool = Field(True, alias="continue")
    """Whether model should continue after processing hook response.
    Usually True unless you want to stop the session."""

    stop_reason: str | None = Field(None, alias="stopReason")
    """If provided with continue=False, stops the session with this message."""

    suppress_output: bool = Field(False, alias="suppressOutput")
    """If True, suppresses the hook's own output (stdout/stderr) from being shown."""

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=None, use_enum_values=True, arbitrary_types_allowed=True
    )


class EditOperation(BaseModel):
    """Individual edit operation for MultiEdit tool.

    Represents a single find-and-replace operation within a MultiEdit sequence.
    """

    old_string: str
    """Exact text to find in the file (must match precisely)."""

    new_string: str
    """Text to replace the old_string with."""

    replace_all: bool = False
    """If True, replace all occurrences; if False, only replace first occurrence."""


class ToolInput(BaseModel):
    """Input parameters for Claude Code file manipulation tools.

    Different tools use different subsets of these fields:
    - Write: file_path, content
    - Edit: file_path, old_string, new_string, replace_all
    - MultiEdit: file_path, edits
    """

    # Common fields
    file_path: str | None = None
    """Path to the file being operated on. May be None for non-file tools."""

    # Write tool fields
    content: str | None = None
    """Full content to write to the file (Write tool only)."""

    # Edit tool fields
    old_string: str | None = None
    """Text to find and replace (Edit tool only)."""

    new_string: str | None = None
    """Replacement text (Edit tool only)."""

    replace_all: bool = False
    """Replace all occurrences if True, first occurrence if False (Edit tool)."""

    # MultiEdit tool fields
    edits: list[EditOperation] | None = None
    """List of edit operations to apply in sequence (MultiEdit tool only)."""


class PatchLine(BaseModel):
    """Represents a hunk in a structured patch (unified diff format).

    This appears in tool responses to show exactly what changed in a file.
    """

    old_start: int = Field(alias="oldStart")
    """Starting line number in the original file."""

    old_lines: int = Field(alias="oldLines")
    """Number of lines in the original file covered by this hunk."""

    new_start: int = Field(alias="newStart")
    """Starting line number in the modified file."""

    new_lines: int = Field(alias="newLines")
    """Number of lines in the modified file covered by this hunk."""

    lines: list[str]
    """The actual diff lines, including context and changes with +/- prefixes."""


class ToolResponse(BaseModel):
    """Response from tool execution (post-hook only).

    Contains information about what actually happened during tool execution,
    including any modifications made by the tool or by auto-fixes.
    """

    # Common fields
    file_path: str | None = Field(None, alias="filePath")
    """Path to the file that was operated on."""

    # Edit/MultiEdit response fields
    old_string: str | None = Field(None, alias="oldString")
    """Original text that was replaced (for Edit operations)."""

    new_string: str | None = Field(None, alias="newString")
    """New text that replaced the old (for Edit operations)."""

    original_file: str | None = Field(None, alias="originalFile")
    """Original file content before any modifications."""

    structured_patch: list[PatchLine] | None = Field(None, alias="structuredPatch")
    """Detailed patch information showing all changes made."""

    user_modified: bool = Field(False, alias="userModified")
    """Set by Claude Code (not the hook) - always False in observed logs.
    Likely tracks if file was externally modified after tool execution."""

    replace_all: bool = Field(False, alias="replaceAll")
    """Whether all occurrences were replaced (for Edit operations)."""


class HookRequest(BaseModel):
    """Request sent from Claude Code to a hook command.

    Contains all context about the tool being executed and the Claude session.
    """

    # Hook metadata fields
    session_id: str | None = None
    """UUID of the current Claude Code session."""

    transcript_path: str | None = None
    """Path to the transcript JSONL file for this session."""

    hook_event_name: Literal["PreToolUse", "PostToolUse"] | None = None
    """Which hook event triggered this invocation."""

    # Tool execution fields
    tool_name: str
    """Name of the tool being executed (Write, Edit, MultiEdit, etc.)."""

    tool_input: ToolInput
    """Input parameters for the tool."""

    tool_response: ToolResponse | dict[str, Any] | None = None
    """Tool execution results (PostToolUse only).
    May be a typed ToolResponse or raw dict for other tools."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
