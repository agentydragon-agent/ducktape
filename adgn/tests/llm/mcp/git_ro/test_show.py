from __future__ import annotations

import json

from pydantic import TypeAdapter
import pytest

from adgn.llm.mcp.git_ro.server import (
    DiffFormat,
    ListSlice,
    ShowInput,
    ShowResult,
)


@pytest.mark.asyncio
async def test_git_show_name_status(git_ro_session) -> None:
    async with git_ro_session() as session:
        res_ns = await session.call_tool(
            name="git_show",
            arguments={
                "payload": ShowInput(
                    object="HEAD",
                    format=DiffFormat.NAME_STATUS,
                    list_slice=ListSlice(offset=0, limit=100),
                ),
            },
        )
        payload_ns = res_ns.structuredContent
        if isinstance(payload_ns, str):
            payload_ns = json.loads(payload_ns)
        ns_union = TypeAdapter(ShowResult).validate_python(payload_ns["result"])
        assert ns_union.type == "name-status"
        assert ns_union.result.items


@pytest.mark.asyncio
async def test_git_show_stat(git_ro_session) -> None:
    async with git_ro_session() as session:
        res_st = await session.call_tool(
            name="git_show",
            arguments={
                "payload": ShowInput(
                    object="HEAD",
                    format=DiffFormat.STAT,
                    list_slice=ListSlice(offset=0, limit=100),
                ),
            },
        )
        payload_st = res_st.structuredContent
        if isinstance(payload_st, str):
            payload_st = json.loads(payload_st)
        st_union = TypeAdapter(ShowResult).validate_python(payload_st["result"])
        assert st_union.type == "stat"
        assert st_union.result.items


@pytest.mark.asyncio
async def test_git_show_patch(git_ro_session) -> None:
    async with git_ro_session() as session:
        res_pt = await session.call_tool(
            name="git_show",
            arguments={"payload": ShowInput(object="HEAD", format=DiffFormat.PATCH)},
        )
        payload_pt = res_pt.structuredContent
        if isinstance(payload_pt, str):
            payload_pt = json.loads(payload_pt)
        pt_union = TypeAdapter(ShowResult).validate_python(payload_pt["result"])
        assert pt_union.type == "patch"
        assert isinstance(pt_union.result.body, str)
