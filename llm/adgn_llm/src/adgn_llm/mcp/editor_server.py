from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..mini_codex.local_server import LocalServer, ToolDef, tool

PYTHON_SUFFIXES = {".py", ".pyi"}


def is_python_path(path: Path) -> bool:
    return path.suffix in PYTHON_SUFFIXES


class DoneResult(BaseModel):
    report: str
    success: bool = True


@dataclass
class FileEditorState:
    file_path: Path
    original: list[str]
    lines: list[str]

    @classmethod
    def load(cls, file_path: str | Path) -> FileEditorState:
        p = Path(file_path)
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        return cls(file_path=p, original=list(lines), lines=lines)

    def save(self) -> None:
        self.file_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


class EditorServer(LocalServer):
    """Stateful in-process MCP-like server exposing file editing tools.

    Tools return structured dicts; no stringly status. Consumers can embed this as a
    "local server" alongside stdio MCP servers via McpManager.
    """

    def __init__(self, file_path: str | Path, name: str = "editor"):
        super().__init__(name=name)
        self.state = FileEditorState.load(file_path)

    # ---------------- Tools (handlers) ----------------
    @tool(
        description="Get file path and line count",
        parameters={"type": "object", "properties": {}},
    )
    def read_info(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "path": str(self.state.file_path),
            "lines": len(self.state.lines),
        }

    @tool(
        description="Read a range of lines (1-based)",
        parameters={
            "type": "object",
            "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["start"],
        },
    )
    def read_line_range(self, args: dict[str, Any]) -> dict[str, Any]:
        start = int(args.get("start"))
        end = int(args.get("end") or start)
        start_idx = max(1, start) - 1
        end_idx = min(len(self.state.lines), end) - 1
        if start_idx < 0 or end_idx >= len(self.state.lines) or start_idx > end_idx:
            return {
                "ok": False,
                "error": f"out of bounds: {start}-{end} (len={len(self.state.lines)})",
            }
        body = "\n".join(
            f"{i + 1:4d}: {self.state.lines[i]}" for i in range(start_idx, end_idx + 1)
        )
        return {"ok": True, "body": body}

    @tool(
        description="Replace exact text (single occurrence)",
        parameters={
            "type": "object",
            "properties": {
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["old_text", "new_text"],
        },
    )
    def replace_text(self, args: dict[str, Any]) -> dict[str, Any]:
        old_text = str(args.get("old_text") or "")
        new_text = str(args.get("new_text") or "")
        content = "\n".join(self.state.lines)
        if not old_text:
            return {"ok": False, "error": "old_text required"}
        if old_text not in content:
            return {"ok": False, "error": "old_text not found"}
        if content.count(old_text) > 1:
            return {
                "ok": False,
                "error": "old_text appears multiple times; be more specific",
            }
        self.state.lines = content.replace(old_text, new_text).splitlines()
        return {"ok": True}

    @tool(
        description="Delete a specific line (1-based)",
        parameters={
            "type": "object",
            "properties": {"line_number": {"type": "integer"}},
            "required": ["line_number"],
        },
    )
    def delete_line(self, args: dict[str, Any]) -> dict[str, Any]:
        line_number = int(args.get("line_number"))
        if line_number < 1 or line_number > len(self.state.lines):
            return {
                "ok": False,
                "error": f"line {line_number} out of bounds (len={len(self.state.lines)})",
            }
        deleted = self.state.lines.pop(line_number - 1)
        return {"ok": True, "deleted": deleted}

    @tool(
        description="Add a line after the given line number (0 inserts at beginning)",
        parameters={
            "type": "object",
            "properties": {
                "line_number": {"type": "integer"},
                "content": {"type": "string"},
            },
            "required": ["line_number", "content"],
        },
    )
    def add_line_after(self, args: dict[str, Any]) -> dict[str, Any]:
        line_number = int(args.get("line_number"))
        content = str(args.get("content") or "")
        if line_number < 0 or line_number > len(self.state.lines):
            return {
                "ok": False,
                "error": f"line {line_number} out of bounds (len={len(self.state.lines)})",
            }
        if line_number == 0:
            self.state.lines.insert(0, content)
            return {"ok": True}
        self.state.lines.insert(line_number, content)
        return {"ok": True}

    @tool(
        description="Save the current buffer to disk",
        parameters={"type": "object", "properties": {}},
    )
    def save(self, _args: dict[str, Any]) -> dict[str, Any]:
        self.state.save()
        return {"ok": True}

    @tool(
        description="Finish editing; runs minimal syntax check for Python files and saves on success",
        parameters={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "report": {"type": "string"},
            },
        },
    )
    def done(self, args: dict[str, Any]) -> dict[str, Any]:
        success = bool(args.get("success", True))
        report = str(args.get("report") or "")
        if success and is_python_path(self.state.file_path):
            # minimal python syntax check

            try:
                ast.parse("\n".join(self.state.lines) + "\n")
            except SyntaxError as e:
                return DoneResult(
                    report=f"Cannot complete: Syntax error line {e.lineno}: {e.msg}",
                    success=False,
                ).model_dump()
        if not success:
            self.state.lines = list(self.state.original)
            return DoneResult(report=report or "aborted", success=False).model_dump()
        self.state.save()
        return DoneResult(report=report or "ok", success=True).model_dump()

    # ---------------- Tool registry ----------------
    def get_tools(self) -> dict[str, ToolDef]:
        """Introspect decorated methods and build the tool registry.

        Keeps tool definitions co-located with implementations via @tool.
        """
        registry: dict[str, ToolDef] = {}
        for attr in dir(self):
            fn = getattr(self, attr)
            name = getattr(fn, "_adgn_tool_name", None)
            if not name:
                continue
            desc = getattr(fn, "_adgn_tool_desc", "")
            schema = getattr(
                fn, "_adgn_tool_schema", {"type": "object", "properties": {}},
            )
            registry[name] = (desc, schema, fn)
        return registry
