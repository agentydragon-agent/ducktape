from __future__ import annotations

import json
from pathlib import Path

import pytest

from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.git_ro.server import (
    make_git_ro_server,
    GIT_RO_SERVER_NAME,
    ShowInput,
    DiffFormat,
    ListSlice,
)


@pytest.mark.asyncio
async def test_git_show_formats(git_repo_factory, git_run) -> None:
    repo: Path = git_repo_factory("repo_show")
    # Create a second commit with a rename and a modification
    (repo / "file1.txt").write_text("hello\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)
    git_run(["git", "commit", "-m", "add file1"], repo)
    # Rename file and modify
    (repo / "file1.txt").rename(repo / "file_renamed.txt")
    (repo / "file_renamed.txt").write_text("hello world\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)
    git_run(["git", "commit", "-m", "rename + modify"], repo)

    spec = make_inproc_slot_spec(make_git_ro_server(repo))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        # name-status
        ns_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        res_ns = await sess.call_tool(
            name=ns_name,
            arguments={
                "payload": ShowInput(
                    object="HEAD", format=DiffFormat.NAME_STATUS, list_slice=ListSlice(offset=0, limit=100)
                ).model_dump()
            },
        )
        payload_ns = res_ns.structuredContent
        if isinstance(payload_ns, str):
            payload_ns = json.loads(payload_ns)
        assert isinstance(payload_ns, dict) and "result" in payload_ns
        ns_union = TypeAdapter(ShowResult).validate_python(payload_ns["result"])
        assert ns_union.type == "name-status"
        items = ns_union.result.items
        assert items, "expected name-status items"

        # stat
        st_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        res_st = await sess.call_tool(
            name=st_name,
            arguments={
                "payload": ShowInput(
                    object="HEAD", format=DiffFormat.STAT, list_slice=ListSlice(offset=0, limit=100)
                ).model_dump()
            },
        )
        payload_st = res_st.structuredContent
        if isinstance(payload_st, str):
            payload_st = json.loads(payload_st)
        if isinstance(payload_st, dict) and "result" in payload_st:
            payload_st = payload_st["result"]
        assert isinstance(payload_st, dict)
        stat_items = payload_st.get("items") or []
        assert stat_items, "expected diffstat items"

        # patch
        pt_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        res_pt = await sess.call_tool(
            name=pt_name,
            arguments={"payload": ShowInput(object="HEAD", format=DiffFormat.PATCH).model_dump()},
        )
        payload_pt = res_pt.structuredContent
        if isinstance(payload_pt, str):
            payload_pt = json.loads(payload_pt)
        if isinstance(payload_pt, dict) and "result" in payload_pt:
            payload_pt = payload_pt["result"]
        assert isinstance(payload_pt, dict)
        assert isinstance(payload_pt.get("body"), str)
