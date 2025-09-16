from __future__ import annotations

import json
from pathlib import Path

import pytest
from adgn_llm.mcp.editor_server import make_editor_mcp
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import McpManager, parse_mcp_function
from hamcrest import anything, assert_that, equal_to, has_entries, instance_of


@pytest.mark.asyncio
async def test_editor_inproc_basic_ops(tmp_path: Path) -> None:
    # Prepare a small Python file
    target = tmp_path / "sample.py"
    target.write_text("x = 1\n", encoding="utf-8")

    # Wire in-proc editor server via FastMCP memory streams → McpManager(specs)
    spec = make_inproc_slot_spec(make_editor_mcp(target))

    async with McpManager({"editor": spec}) as mcp:
        # Namespaced tools should be advertised
        specs = await mcp.list_tools()
        names = [s.get("name") for s in specs]
        assert any(n == "mcp__editor__read_info" for n in names)
        assert any(n == "mcp__editor__replace_text" for n in names)
        assert any(n == "mcp__editor__done" for n in names)

        # read_info works
        server, tool = parse_mcp_function("mcp__editor__read_info")
        sess = await mcp.get_session(server)
        res = await sess.call_tool(name=tool, arguments={})
        info = res.structuredContent or {}
        assert_that(info, instance_of(dict))
        assert_that(info, has_entries(ok=True, path=anything(), lines=1))
        assert_that(Path(str(info["path"])), equal_to(target))

        # replace_text modifies buffer (x=1 → x=2)
        server, tool = parse_mcp_function("mcp__editor__replace_text")
        res = await sess.call_tool(
            name=tool,
            arguments={"old_text": "x = 1", "new_text": "x = 2"},
        )
        sc = res.structuredContent or {}
        assert_that(sc, instance_of(dict))
        assert_that(sc, has_entries(ok=True))

        # done(success=True) runs syntax check for .py and saves
        server, tool = parse_mcp_function("mcp__editor__done")
        res = await sess.call_tool(name=tool, arguments={"payload": {"outcome": "success", "summary": ""}})
        payload = res.structuredContent
        # allow either dict or pydantic-like converted dict
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload is not None and isinstance(payload, dict)
        result_obj = payload.get("result", payload)
        assert_that(result_obj, has_entries(kind="Success"))

    # File should be persisted with new content
    assert target.read_text(encoding="utf-8") == "x = 2\n"
