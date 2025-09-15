from __future__ import annotations

import json
import pytest
from pydantic import TypeAdapter

from adgn_llm.mini_codex.mcp_manager import build_mcp_function, McpManager
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.git_ro.server import (
    TextPage,
    TextSlice,
    DiffInput,
    GIT_RO_SERVER_NAME,
    DiffResult,
    PatchResult,
    make_git_ro_server,
)


@pytest.mark.asyncio
async def test_git_diff_patch_first_page(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        res = await m.call_tool(
            build_mcp_function(GIT_RO_SERVER_NAME, "git_diff"),
            {
                "payload": DiffInput(
                    staged=True, unified=0, slice=TextSlice(offset_chars=0, max_chars=2000)
                ).model_dump()
            },
        )
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        union = TypeAdapter(DiffResult).validate_python(payload["result"])
        assert isinstance(union, PatchResult)
        page1 = union.result
        assert isinstance(page1, TextPage)
        assert page1.truncated is True
        assert isinstance(page1.next_offset, int) and page1.next_offset > 0


@pytest.mark.asyncio
async def test_git_diff_patch_second_page(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        # First page to get next_offset
        res1 = await m.call_tool(
            build_mcp_function(GIT_RO_SERVER_NAME, "git_diff"),
            {
                "payload": DiffInput(
                    staged=True, unified=0, slice=TextSlice(offset_chars=0, max_chars=2000)
                ).model_dump()
            },
        )
        payload1 = res1.structuredContent
        if isinstance(payload1, str):
            payload1 = json.loads(payload1)
        union1 = TypeAdapter(DiffResult).validate_python(payload1["result"])
        next_offset = union1.result.next_offset or 0

        # Second page
        res2 = await m.call_tool(
            build_mcp_function(GIT_RO_SERVER_NAME, "git_diff"),
            {
                "payload": DiffInput(
                    staged=True, unified=0, slice=TextSlice(offset_chars=next_offset, max_chars=2000)
                ).model_dump()
            },
        )
        payload2 = res2.structuredContent
        if isinstance(payload2, str):
            payload2 = json.loads(payload2)
        union2 = TypeAdapter(DiffResult).validate_python(payload2["result"])
        page2 = union2.result
        assert isinstance(page2, TextPage)
        assert page2.total_chars == union1.result.total_chars
        assert page2.body != union1.result.body
