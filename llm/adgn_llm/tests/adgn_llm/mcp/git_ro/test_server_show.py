from __future__ import annotations

import json
import pytest
from pydantic import TypeAdapter

from adgn_llm.mini_codex.mcp_manager import build_mcp_function, McpManager
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.git_ro.server import (
    GIT_RO_SERVER_NAME,
    ShowInput,
    DiffFormat,
    ListSlice,
    ShowResult,
    make_git_ro_server,
)


@pytest.mark.asyncio
async def test_git_show_name_status(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        ns_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        _, ns_tool = m.resolve_function(ns_name)
        res_ns = await sess.call_tool(
            name=ns_tool,
            arguments={
                "payload": ShowInput(
                    object="HEAD", format=DiffFormat.NAME_STATUS, list_slice=ListSlice(offset=0, limit=100)
                ).model_dump()
            },
        )
        payload_ns = res_ns.structuredContent
        if isinstance(payload_ns, str):
            payload_ns = json.loads(payload_ns)
        ns_union = TypeAdapter(ShowResult).validate_python(payload_ns["result"])
        assert ns_union.type == "name-status"
        assert ns_union.result.items


@pytest.mark.asyncio
async def test_git_show_stat(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        st_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        _, st_tool = m.resolve_function(st_name)
        res_st = await sess.call_tool(
            name=st_tool,
            arguments={
                "payload": ShowInput(
                    object="HEAD", format=DiffFormat.STAT, list_slice=ListSlice(offset=0, limit=100)
                ).model_dump()
            },
        )
        payload_st = res_st.structuredContent
        if isinstance(payload_st, str):
            payload_st = json.loads(payload_st)
        st_union = TypeAdapter(ShowResult).validate_python(payload_st["result"])
        assert st_union.type == "stat"
        assert st_union.result.items


@pytest.mark.asyncio
async def test_git_show_patch(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        pt_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        _, pt_tool = m.resolve_function(pt_name)
        res_pt = await sess.call_tool(
            name=pt_tool,
            arguments={"payload": ShowInput(object="HEAD", format=DiffFormat.PATCH).model_dump()},
        )
        payload_pt = res_pt.structuredContent
        if isinstance(payload_pt, str):
            payload_pt = json.loads(payload_pt)
        pt_union = TypeAdapter(ShowResult).validate_python(payload_pt["result"])
        assert pt_union.type == "patch"
        assert isinstance(pt_union.result.body, str)
