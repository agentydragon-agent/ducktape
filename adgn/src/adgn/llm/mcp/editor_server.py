from __future__ import annotations

import ast
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adgn.llm.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.llm.mcp._shared.fastmcp_helpers import mcp_flat_model
from pydantic import BaseModel, ConfigDict

PYTHON_SUFFIXES = {".py", ".pyi"}


def is_python_path(path: Path) -> bool:
    return path.suffix in PYTHON_SUFFIXES


# -------------------------- Typed inputs/outputs -----------------------------


class ReadInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadInfoResult(BaseModel):
    ok: bool
    path: str
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


class DoneInput(BaseModel):
    """Single-argument payload for the done() tool.

    outcome: explicit algebraic outcome selector ("success"|"failure")
    summary: optional human-readable note to include in the result
    """

    outcome: Literal["success", "failure"] = "success"
    summary: str | None = None

    # Strict: no legacy aliases accepted (force new format everywhere)
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


def _load_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def make_editor_mcp(file_path: str | Path, *, name: str = "editor") -> SafeFastMCP:
    p = Path(file_path)
    text = _load_text(p)
    state = EditorState(file_path=p, content=text, original=text)

    @asynccontextmanager
    async def lifespan(_server: SafeFastMCP):  # yields EditorState
        try:
            yield state
        finally:
            # no-op; tools manage persistence explicitly
            pass

    mcp = SafeFastMCP(name, instructions="In-process file editor", lifespan=lifespan)

    @mcp_flat_model(
        mcp,
        name="read_info",
        title="Read file info",
        description="Return basic info about the current file",
        structured_output=True,
    )
    def read_info(input: ReadInfoArgs) -> ReadInfoResult:
        return ReadInfoResult(
            ok=True,
            path=str(state.file_path),
            lines=len(state.content.splitlines()),
        )

    @mcp_flat_model(
        mcp,
        name="read_line_range",
        title="Read line range",
        description="Return lines in the given [start,end] (1-based)",
        structured_output=True,
    )
    def read_line_range(input: ReadLineRangeArgs) -> ReadLineRangeResult:
        lines = state.content.splitlines()
        end = input.start if input.end is None else input.end
        start_idx = max(1, input.start) - 1
        end_idx = min(len(lines), end) - 1
        if start_idx < 0 or end_idx >= len(lines) or start_idx > end_idx:
            return ReadLineRangeResult(
                ok=False,
                error=f"out of bounds: {input.start}-{end} (len={len(lines)})",
            )
        body = "\n".join(
            f"{i + 1:4d}: {lines[i]}" for i in range(start_idx, end_idx + 1)
        )
        return ReadLineRangeResult(ok=True, body=body)

    @mcp_flat_model(
        mcp,
        name="replace_text",
        title="Replace text",
        description="Replace one occurrence of old_text with new_text (fails if multiple)",
        structured_output=True,
    )
    def replace_text(input: ReplaceTextArgs) -> ReplaceTextResult:
        if not input.old_text:
            return ReplaceTextResult(ok=False, error="old_text required")
        if input.old_text not in state.content:
            return ReplaceTextResult(ok=False, error="old_text not found")
        if state.content.count(input.old_text) > 1:
            return ReplaceTextResult(
                ok=False, error="old_text appears multiple times; be more specific"
            )
        state.content = state.content.replace(input.old_text, input.new_text)
        return ReplaceTextResult(ok=True)

    @mcp_flat_model(
        mcp,
        name="replace_text_all",
        title="Replace all",
        description="Replace all occurrences of old_text with new_text",
        structured_output=True,
    )
    def replace_text_all(input: ReplaceTextAllArgs) -> ReplaceTextAllResult:
        if not input.old_text:
            return ReplaceTextAllResult(ok=False, error="old_text required")
        if input.old_text not in state.content:
            return ReplaceTextAllResult(ok=False, error="old_text not found")
        count = state.content.count(input.old_text)
        state.content = state.content.replace(input.old_text, input.new_text)
        return ReplaceTextAllResult(ok=True, replacements=count)

    @mcp_flat_model(
        mcp,
        name="delete_line",
        title="Delete line",
        description="Delete a specific line (1-based)",
        structured_output=True,
    )
    def delete_line(input: DeleteLineArgs) -> DeleteLineResult:
        lines = state.content.splitlines()
        if input.line_number < 1 or input.line_number > len(lines):
            return DeleteLineResult(
                ok=False,
                error=f"line {input.line_number} out of bounds (len={len(lines)})",
            )
        deleted = lines.pop(input.line_number - 1)
        state.content = "\n".join(lines)
        return DeleteLineResult(ok=True, deleted=deleted)

    @mcp_flat_model(
        mcp,
        name="add_line_after",
        title="Add line after",
        description="Insert a line after the given line (0 inserts at start)",
        structured_output=True,
    )
    def add_line_after(input: AddLineAfterArgs) -> AddLineAfterResult:
        lines = state.content.splitlines()
        if input.line_number < 0 or input.line_number > len(lines):
            return AddLineAfterResult(
                ok=False,
                error=f"line {input.line_number} out of bounds (len={len(lines)})",
            )
        if input.line_number == 0:
            lines.insert(0, input.content)
        else:
            lines.insert(input.line_number, input.content)
        state.content = "\n".join(lines)
        return AddLineAfterResult(ok=True)

    @mcp_flat_model(
        mcp,
        name="save",
        title="Save file",
        description="Persist current buffer to disk",
        structured_output=True,
    )
    def save(input: SaveArgs) -> SaveResult:
        state.file_path.write_text(state.content.rstrip("\n") + "\n", encoding="utf-8")
        return SaveResult(ok=True)

    @mcp_flat_model(
        mcp,
        name="done",
        title="Finish editing",
        description="Finish the editing session with Success|Failure",
        structured_output=True,
    )
    def done(input: DoneInput) -> DoneResponse:
        """Finish the editing session with Success|Failure (legacy shape kept for tests).

        - On outcome=="success": for Python files, perform a quick syntax check; if it fails, do NOT save,
          revert in-memory buffer to original, and return Failure with a summary.
        - On outcome=="failure": revert in-memory buffer to original and return Failure with the given summary.
        - On success with no syntax errors: save current buffer to disk and return Success.
        """
        if input.outcome == "success":
            if is_python_path(state.file_path):
                try:
                    ast.parse(state.content + "\n")
                except SyntaxError as e:
                    # Revert in-memory buffer on failure so callers can inspect original state
                    state.content = state.original
                    return Failure(
                        summary=f"Cannot complete: syntax error line {e.lineno}: {e.msg}",
                    )
            # Save edited contents
            state.file_path.write_text(
                state.content.rstrip("\n") + "\n",
                encoding="utf-8",
            )
            return Success(summary=input.summary)
        # Explicit failure: revert in-memory buffer
        state.content = state.original
        return Failure(summary=input.summary)

    return mcp
