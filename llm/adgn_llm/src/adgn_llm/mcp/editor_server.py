from __future__ import annotations


import ast
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

PYTHON_SUFFIXES = {".py", ".pyi"}


def is_python_path(path: Path) -> bool:
    return path.suffix in PYTHON_SUFFIXES


class DoneInput(BaseModel):
    """Single-argument payload for the done() tool.

    outcome: explicit algebraic outcome selector ("success"|"failure")
    summary: short human-readable summary
    """

    outcome: Literal["success", "failure"] = "success"
    summary: str = ""

    # Strict: no legacy aliases accepted (force new format everywhere)
    model_config = ConfigDict(extra="forbid")


class Success(BaseModel):
    kind: Literal["Success"] = "Success"
    summary: str


class Failure(BaseModel):
    kind: Literal["Failure"] = "Failure"
    summary: str


DoneResponse = Annotated[Success | Failure, Field(discriminator="kind")]


# Canonical FastMCP server: state via lifespan; lines derived from content
@dataclass
class EditorState:
    file_path: Path
    content: str  # current buffer
    original: str  # original buffer for aborts


def _load_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def make_editor_mcp(file_path: str | Path, *, name: str = "editor") -> FastMCP:
    p = Path(file_path)
    text = _load_text(p)
    state = EditorState(file_path=p, content=text, original=text)

    @asynccontextmanager
    async def lifespan(_server: FastMCP):  # yields EditorState
        try:
            yield state
        finally:
            # no-op; tools manage persistence explicitly
            pass

    mcp = FastMCP(name, instructions="In-process file editor", lifespan=lifespan)

    @mcp.tool()
    def read_info() -> dict[str, Any]:
        return {
            "ok": True,
            "path": str(state.file_path),
            "lines": len(state.content.splitlines()),
        }

    @mcp.tool()
    def read_line_range(start: int, end: int | None = None) -> dict[str, Any]:
        lines = state.content.splitlines()
        end = start if end is None else end
        start_idx = max(1, start) - 1
        end_idx = min(len(lines), end) - 1
        if start_idx < 0 or end_idx >= len(lines) or start_idx > end_idx:
            return {
                "ok": False,
                "error": f"out of bounds: {start}-{end} (len={len(lines)})",
            }
        body = "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(start_idx, end_idx + 1))
        return {"ok": True, "body": body}

    @mcp.tool()
    def replace_text(old_text: str, new_text: str) -> dict[str, Any]:
        if not old_text:
            return {"ok": False, "error": "old_text required"}
        if old_text not in state.content:
            return {"ok": False, "error": "old_text not found"}
        if state.content.count(old_text) > 1:
            return {
                "ok": False,
                "error": "old_text appears multiple times; be more specific",
            }
        state.content = state.content.replace(old_text, new_text)
        return {"ok": True}

    @mcp.tool()
    def replace_text_all(old_text: str, new_text: str) -> dict[str, Any]:
        if not old_text:
            return {"ok": False, "error": "old_text required"}
        if old_text not in state.content:
            return {"ok": False, "error": "old_text not found"}
        count = state.content.count(old_text)
        state.content = state.content.replace(old_text, new_text)
        return {"ok": True, "replacements": count}

    @mcp.tool()
    def delete_line(line_number: int) -> dict[str, Any]:
        lines = state.content.splitlines()
        if line_number < 1 or line_number > len(lines):
            return {
                "ok": False,
                "error": f"line {line_number} out of bounds (len={len(lines)})",
            }
        deleted = lines.pop(line_number - 1)
        state.content = "\n".join(lines)
        return {"ok": True, "deleted": deleted}

    @mcp.tool()
    def add_line_after(line_number: int, content: str) -> dict[str, Any]:
        lines = state.content.splitlines()
        if line_number < 0 or line_number > len(lines):
            return {
                "ok": False,
                "error": f"line {line_number} out of bounds (len={len(lines)})",
            }
        if line_number == 0:
            lines.insert(0, content)
        else:
            lines.insert(line_number, content)
        state.content = "\n".join(lines)
        return {"ok": True}

    @mcp.tool()
    def save() -> dict[str, Any]:
        state.file_path.write_text(state.content.rstrip("\n") + "\n", encoding="utf-8")
        return {"ok": True}

    @mcp.tool()
    def done(payload: DoneInput) -> DoneResponse:
        """Finish the editing session (typed: DoneInput → Success|Failure).

        - On outcome=="success": for Python files, perform a quick syntax check; if it fails, do NOT save,
          revert in-memory buffer to original, and return Failure with a summary.
        - On outcome=="failure": revert in-memory buffer to original and return Failure with the given summary.
        - On success with no syntax errors: save current buffer to disk and return Success.
        """
        if payload.outcome == "success":
            if is_python_path(state.file_path):
                try:
                    ast.parse(state.content + "\n")
                except SyntaxError as e:
                    # Revert in-memory buffer on failure so callers can inspect original state
                    state.content = state.original
                    return Failure(summary=f"Cannot complete: syntax error line {e.lineno}: {e.msg}")
            # Save edited contents
            state.file_path.write_text(state.content.rstrip("\n") + "\n", encoding="utf-8")
            return Success(summary=(payload.summary or "ok"))
        # Explicit failure: revert in-memory buffer
        state.content = state.original
        return Failure(summary=(payload.summary or "aborted"))

    return mcp
