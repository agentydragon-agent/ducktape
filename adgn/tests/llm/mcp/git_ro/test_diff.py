from __future__ import annotations

from contextlib import AsyncExitStack
import json

from pydantic import TypeAdapter
import pytest

from adgn.llm.mcp.git_ro.server import (
    DiffInput,
    DiffResult,
    PatchResult,
    TextPage,
    TextSlice,
    make_git_ro_server,
)
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_git_diff_patch_first_page(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        session = slot.session
        res = await session.call_tool(
            name="git_diff",
            arguments={
                "payload": DiffInput(
                    staged=True,
                    unified=0,
                    slice=TextSlice(offset_chars=0, max_chars=2000),
                ),
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
        assert isinstance(page1.next_offset, int)
        assert page1.next_offset > 0


@pytest.mark.asyncio
async def test_git_diff_patch_second_page(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        session = slot.session
        # First page to get next_offset
        res1 = await session.call_tool(
            name="git_diff",
            arguments={
                "payload": DiffInput(
                    staged=True,
                    unified=0,
                    slice=TextSlice(offset_chars=0, max_chars=2000),
                ),
            },
        )
        payload1 = res1.structuredContent
        if isinstance(payload1, str):
            payload1 = json.loads(payload1)
        union1 = TypeAdapter(DiffResult).validate_python(payload1["result"])
        next_offset = union1.result.next_offset or 0

        # Second page
        res2 = await session.call_tool(
            name="git_diff",
            arguments={
                "payload": DiffInput(
                    staged=True,
                    unified=0,
                    slice=TextSlice(offset_chars=next_offset, max_chars=2000),
                ),
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
