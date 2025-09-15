#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

import pytest

from adgn_llm.mcp.editor_server import make_editor_mcp, is_python_path
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import McpManager


@pytest.fixture
def editor_session():
    """Factory fixture yielding an in-proc FastMCP client session context manager for a given path."""

    @asynccontextmanager
    async def _open(p: Path):
        # Open a one-off in-proc MCP session via the standard wrapper
        spec = make_inproc_slot_spec(make_editor_mcp(p))
        async with McpManager({"editor": spec}) as mcp:
            sess = await mcp.get_session("editor")
            yield sess

    return _open


def test_is_python_path() -> None:
    assert is_python_path(Path("foo.py"))
    assert is_python_path(Path("bar.pyi"))
    assert not is_python_path(Path("README.md"))
    assert not is_python_path(Path("Makefile"))


@pytest.mark.asyncio
async def test_done_for_non_python_no_syntax_check(tmp_path: Path, editor_session) -> None:
    p = tmp_path / "note.md"
    p.write_text("hello\n", encoding="utf-8")

    async with editor_session(p) as sess:
        # Append a line after the first line (1-based after = insert at index 1)
        await sess.call_tool(name="add_line_after", arguments={"line_number": 1, "content": "world"})
        # Finish successfully; should not run python syntax checks
        res = await sess.call_tool(name="done", arguments={"success": True, "report": "ok"})
        data = res.structuredContent or {}
        assert data["kind"] == "Success"
        assert data["summary"] == "ok"

    # file saved with edits
    assert p.read_text(encoding="utf-8") == "hello\nworld\n"


@pytest.mark.asyncio
async def test_done_python_syntax_failure_returns_structured_failure(tmp_path: Path, editor_session) -> None:
    p = tmp_path / "bad.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")  # start valid

    async with editor_session(p) as sess:
        # Introduce a syntax error by replacing the function header
        await sess.call_tool(name="replace_text", arguments={"old_text": "def f():", "new_text": "def f(:"})
        res = await sess.call_tool(name="done", arguments={"success": True, "report": "finish"})
        data = res.structuredContent or {}
        assert data["kind"] == "Failure"
        assert "Cannot complete" in data["summary"]

    # file on disk should not have been overwritten with bad content
    assert p.read_text(encoding="utf-8") == "def f():\n    return 1\n"


@pytest.mark.asyncio
async def test_done_explicit_failure_reverts_in_memory(tmp_path: Path, editor_session) -> None:
    p = tmp_path / "file.txt"
    p.write_text("A\n", encoding="utf-8")

    async with editor_session(p) as sess:
        # Stage change to "B" in-memory: delete line 1 and insert B at start
        await sess.call_tool(name="delete_line", arguments={"line_number": 1})
        await sess.call_tool(name="add_line_after", arguments={"line_number": 0, "content": "B"})
        res = await sess.call_tool(name="done", arguments={"success": False, "report": "abort"})
        data = res.structuredContent or {}
        assert data["kind"] == "Failure"
        assert data["summary"] == "abort"
        # Ensure in-memory state reverted by reading current first line
        rr = await sess.call_tool(name="read_line_range", arguments={"start": 1, "end": 1})
        body = (rr.structuredContent or {}).get("body", "")
        assert "A" in body

    # file on disk unchanged
    assert p.read_text(encoding="utf-8") == "A\n"
