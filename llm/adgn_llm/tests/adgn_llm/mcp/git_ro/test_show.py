from __future__ import annotations

import json
import pytest
from pydantic import TypeAdapter

from adgn_llm.mini_codex.mcp_manager import build_mcp_function, McpManager
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import parse_mcp_function
from adgn_llm.mcp.helpers import make_openai_function_call_full
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
        # Use helper to build a model-like function_call and then route via McpManager
        func = make_openai_function_call_full(
            GIT_RO_SERVER_NAME,
            "git_show",
            {
                "payload": ShowInput(
                    object="HEAD", format=DiffFormat.NAME_STATUS, list_slice=ListSlice(offset=0, limit=100)
                ),
            },
        )
        res_ns = await m.call_tool(func["name"], arguments=func["arguments"])
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
        st_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        _, st_tool = parse_mcp_function(st_name)
        res_st = await m.call_tool(
            build_mcp_function(GIT_RO_SERVER_NAME, st_tool),
            arguments={
                "payload": ShowInput(object="HEAD", format=DiffFormat.STAT, list_slice=ListSlice(offset=0, limit=100)),
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
        pt_name = build_mcp_function(GIT_RO_SERVER_NAME, "git_show")
        _, pt_tool = parse_mcp_function(pt_name)
        res_pt = await m.call_tool(
            build_mcp_function(GIT_RO_SERVER_NAME, pt_tool),
            arguments={"payload": ShowInput(object="HEAD", format=DiffFormat.PATCH)},
        )
        payload_pt = res_pt.structuredContent
        if isinstance(payload_pt, str):
            payload_pt = json.loads(payload_pt)
        pt_union = TypeAdapter(ShowResult).validate_python(payload_pt["result"])
        assert pt_union.type == "patch"
        assert isinstance(pt_union.result.body, str)
