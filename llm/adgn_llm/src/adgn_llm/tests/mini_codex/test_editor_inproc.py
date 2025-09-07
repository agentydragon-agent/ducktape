from __future__ import annotations

import json
from pathlib import Path

import pytest

from adgn_llm.mcp.editor_server import make_editor_mcp
from adgn_llm.mcp.inproc import fastmcp_inproc_client
from adgn_llm.mini_codex.mcp_manager import (
    McpManager,
    ServerSlot,
    session_opener,
)


@pytest.mark.asyncio
async def test_editor_inproc_basic_ops(tmp_path: Path) -> None:
    # Prepare a small Python file
    target = tmp_path / "sample.py"
    target.write_text("x = 1\n", encoding="utf-8")

    # Wire in-proc editor server via FastMCP memory streams → McpManager(slots)
    open_fn = session_opener(lambda: fastmcp_inproc_client(lambda: make_editor_mcp(target)))
    slots = {"editor": ServerSlot(name="editor", open_fn=open_fn)}

    async with McpManager(slots) as mcp:
        # Namespaced tools should be advertised
        specs = await mcp.list_tools()
        names = [s.get("name") for s in specs]
        assert any(n == "mcp__editor__read_info" for n in names)
        assert any(n == "mcp__editor__replace_text" for n in names)
        assert any(n == "mcp__editor__done" for n in names)

        # read_info works
        server, tool = mcp.resolve_function("mcp__editor__read_info")
        sess = await mcp.get_session(server)
        res = await sess.call_tool(name=tool, arguments={})
        info = res.structuredContent
        assert info["ok"] is True
        assert Path(info["path"]) == target
        assert info["lines"] == 1

        # replace_text modifies buffer (x=1 → x=2)
        server, tool = mcp.resolve_function("mcp__editor__replace_text")
        res = await sess.call_tool(
            name=tool,
            arguments={"old_text": "x = 1", "new_text": "x = 2"},
        )
        assert res.structuredContent.get("ok") is True

        # done(success=True) runs syntax check for .py and saves
        server, tool = mcp.resolve_function("mcp__editor__done")
        res = await sess.call_tool(name=tool, arguments={"success": True})
        payload = res.structuredContent
        # allow either dict or pydantic-like converted dict
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload.get("success") is True

    # File should be persisted with new content
    assert target.read_text(encoding="utf-8") == "x = 2\n"
