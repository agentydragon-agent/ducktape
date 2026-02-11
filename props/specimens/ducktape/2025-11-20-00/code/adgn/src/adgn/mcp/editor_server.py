from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

PYTHON_SUFFIXES = {".py", ".pyi"}


def is_python_path(path: Path) -> bool:
    return path.suffix in PYTHON_SUFFIXES


# -------------------------- Typed inputs/outputs -----------------------------


class ReadInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadInfoResult(BaseModel):
    ok: bool
    path: Path
    lines: int
    model_config = ConfigDict(extra="forbid")


class ReadLineRangeArgs(BaseModel):
    start: int
    end: int | None = None
    model_config = ConfigDict(extra="forbid")


class ReadLineRangeResult(BaseModel):
    ok: bool
    body: str | None = None
    error: str | None = None
    model_config = ConfigDict(extra="forbid")


class ReplaceTextArgs(BaseModel):
    old_text: str
    new_text: str
    model_config = ConfigDict(extra="forbid")


class ReplaceTextResult(BaseModel):
    ok: bool
    error: str | None = None
    model_config = ConfigDict(extra="forbid")


class ReplaceTextAllArgs(BaseModel):
    old_text: str
    new_text: str
    model_config = ConfigDict(extra="forbid")


class ReplaceTextAllResult(BaseModel):
    ok: bool
    replacements: int | None = None
    error: str | None = None
    model_config = ConfigDict(extra="forbid")


class DeleteLineArgs(BaseModel):
    line_number: int
    model_config = ConfigDict(extra="forbid")


class DeleteLineResult(BaseModel):
    ok: bool
    deleted: str | None = None
    error: str | None = None
    model_config = ConfigDict(extra="forbid")


class AddLineAfterArgs(BaseModel):
    line_number: int
    content: str
    model_config = ConfigDict(extra="forbid")


class AddLineAfterResult(BaseModel):
    ok: bool
    error: str | None = None
    model_config = ConfigDict(extra="forbid")


class SaveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaveResult(BaseModel):
    ok: bool
    model_config = ConfigDict(extra="forbid")


class EditorOutcome(str, Enum):
    """Explicit outcome selector for the editor's done() tool."""

    SUCCESS = "success"
    FAILURE = "failure"


class DoneInput(BaseModel):
    """Single-argument payload for the done() tool.

    - outcome: enum EditorOutcome (success|failure)
    - summary: optional note included in the result
    """

    outcome: EditorOutcome = EditorOutcome.SUCCESS
    summary: str | None = None

    model_config = ConfigDict(extra="forbid")


class Success(BaseModel):
    kind: Literal["Success"] = "Success"
    summary: str | None = None
    model_config = ConfigDict(extra="forbid")


class Failure(BaseModel):
    kind: Literal["Failure"] = "Failure"
    summary: str | None = None
    model_config = ConfigDict(extra="forbid")


DoneResponse = Success | Failure


# ------------------------------ Server --------------------------------------


@dataclass
class EditorState:
    file_path: Path
    content: str  # current buffer
    original: str  # original buffer for aborts


## Simple file IO helpers are inlined at call sites to avoid trivial indirection


def _build_editor_tools(mcp: NotifyingFastMCP, state: EditorState) -> None:
    @mcp.flat_model()
    def read_info(input: ReadInfoArgs) -> ReadInfoResult:
        """Return basic info about the current file."""
        return ReadInfoResult(ok=True, path=state.file_path, lines=len(state.content.splitlines()))

    @mcp.flat_model()
    def read_line_range(input: ReadLineRangeArgs) -> ReadLineRangeResult:
        """Return lines in the given [start,end] (1-based)."""
        lines = state.content.splitlines()
        end = input.start if input.end is None else input.end
        start_idx = max(1, input.start) - 1
        end_idx = min(len(lines), end) - 1
        if start_idx < 0 or end_idx >= len(lines) or start_idx > end_idx:
            return ReadLineRangeResult(ok=False, error=f"out of bounds: {input.start}-{end} (len={len(lines)})")
        body = "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(start_idx, end_idx + 1))
        return ReadLineRangeResult(ok=True, body=body)

    def _do_replace(old_text: str, new_text: str, replace_all: bool) -> tuple[bool, int, str | None]:
        if not old_text:
            return False, 0, "old_text required"
        if old_text not in state.content:
            return False, 0, "old_text not found"
        count = state.content.count(old_text)
        if not replace_all and count > 1:
            return False, 0, "old_text appears multiple times; be more specific"
        state.content = (
            state.content.replace(old_text, new_text) if replace_all else state.content.replace(old_text, new_text, 1)
        )
        return True, (count if replace_all else 1), None

    @mcp.flat_model()
    def replace_text(input: ReplaceTextArgs) -> ReplaceTextResult:
        """Replace one occurrence of old_text with new_text (fails if multiple)."""
        ok, _count, err = _do_replace(input.old_text, input.new_text, False)
        return ReplaceTextResult(ok=ok, error=err)

    @mcp.flat_model()
    def replace_text_all(input: ReplaceTextAllArgs) -> ReplaceTextAllResult:
        """Replace all occurrences of old_text with new_text."""
        ok, count, err = _do_replace(input.old_text, input.new_text, True)
        return ReplaceTextAllResult(ok=ok, replacements=(count if ok else None), error=err)

    @mcp.flat_model()
    def delete_line(input: DeleteLineArgs) -> DeleteLineResult:
        """Delete a specific line (1-based)."""
        lines = state.content.splitlines()
        if input.line_number < 1 or input.line_number > len(lines):
            return DeleteLineResult(ok=False, error=f"line {input.line_number} out of bounds (len={len(lines)})")
        deleted = lines.pop(input.line_number - 1)
        state.content = "\n".join(lines)
        return DeleteLineResult(ok=True, deleted=deleted)

    @mcp.flat_model()
    def add_line_after(input: AddLineAfterArgs) -> AddLineAfterResult:
        """Insert a line after the given line (0 inserts at start)."""
        lines = state.content.splitlines()
        if input.line_number < 0 or input.line_number > len(lines):
            return AddLineAfterResult(ok=False, error=f"line {input.line_number} out of bounds (len={len(lines)})")
        if input.line_number == 0:
            lines.insert(0, input.content)
        else:
            lines.insert(input.line_number, input.content)
        state.content = "\n".join(lines)
        return AddLineAfterResult(ok=True)

    @mcp.flat_model()
    def save(input: SaveArgs) -> SaveResult:
        """Persist current buffer to disk."""
        state.file_path.write_text(state.content.rstrip("\n") + "\n", encoding="utf-8")
        return SaveResult(ok=True)

    @mcp.flat_model()
    def done(input: DoneInput) -> DoneResponse:
        """Finish the editing session with Success|Failure using early bailouts.

        - On failure: revert immediately and return Failure.
        - On success: for Python files, syntax-check; on error, revert and return Failure.
          Otherwise, save and return Success.
        """
        if input.outcome is EditorOutcome.FAILURE:
            state.content = state.original
            return Failure(summary=input.summary)

        # Success path
        if is_python_path(state.file_path):
            try:
                ast.parse(state.content + "\n")
            except SyntaxError as e:
                state.content = state.original
                return Failure(summary=f"Cannot complete: syntax error line {e.lineno}: {e.msg}")

        state.file_path.write_text(state.content.rstrip("\n") + "\n", encoding="utf-8")
        return Success(summary=input.summary)


async def attach_editor(comp: Compositor, file_path: Path, *, name: str = "editor"):
    """Attach the editor MCP in-proc (encapsulated)."""
    server = make_editor_server(file_path, name=name)
    await comp.mount_inproc(name, server)
    return server


def make_editor_server(file_path: Path, *, name: str = "editor") -> NotifyingFastMCP:
    """Construct an in-process editor server for the given file with standard tools."""
    text = file_path.read_text(encoding="utf-8")
    state = EditorState(file_path=file_path, content=text, original=text)
    server = NotifyingFastMCP(name, instructions="In-process file editor")
    _build_editor_tools(server, state)
    return server
