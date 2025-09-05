#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from adgn_llm.mcp.editor_server import EditorServer, is_python_path


def test_is_python_path() -> None:
    assert is_python_path(Path("foo.py"))
    assert is_python_path(Path("bar.pyi"))
    assert not is_python_path(Path("README.md"))
    assert not is_python_path(Path("Makefile"))


def test_done_for_non_python_no_syntax_check(tmp_path: Path) -> None:
    p = tmp_path / "note.md"
    p.write_text("hello\n")
    ed = EditorServer(str(p))
    # apply an edit in-memory
    ed.state.lines.append("world")
    # Finish successfully; should not run python syntax checks
    res = ed.done({"success": True, "report": "ok"})
    # EditorServer.done returns a structured dict, but ensure it's JSON-serializable for parity
    data = json.loads(json.dumps(res))
    assert data["success"] is True
    assert data["report"] == "ok"
    # file saved with edits
    assert p.read_text(encoding="utf-8") == "hello\nworld\n"


def test_done_python_syntax_failure_returns_structured_failure(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")  # start valid
    ed = EditorServer(str(p))
    # introduce a syntax error in-memory
    ed.state.lines = ["def f(:", "    return 1"]
    res = ed.done({"success": True, "report": "finish"})
    data = json.loads(json.dumps(res))
    assert data["success"] is False
    assert "Cannot complete" in data["report"]
    # file on disk should not have been overwritten with bad content
    assert p.read_text(encoding="utf-8") == "def f():\n    return 1\n"


def test_done_explicit_failure_reverts_in_memory(tmp_path: Path) -> None:
    p = tmp_path / "file.txt"
    p.write_text("A\n", encoding="utf-8")
    ed = EditorServer(str(p))
    ed.state.lines = ["B"]  # staged change
    res = ed.done({"success": False, "report": "abort"})
    data = json.loads(json.dumps(res))
    assert data["success"] is False
    assert data["report"] == "abort"
    # in-memory state reverted
    assert ed.state.lines == ed.state.original
    # file on disk unchanged
    assert p.read_text(encoding="utf-8") == "A\n"
