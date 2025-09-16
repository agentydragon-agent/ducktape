from __future__ import annotations

import json

import pytest
from adgn_llm.mcp.git_ro.server import LogInput, StatusPage, TextPage, TextSlice
from pydantic import TypeAdapter


@pytest.mark.asyncio
async def test_git_status_basic(git_ro_session) -> None:
    async with git_ro_session() as session:
        res = await session.call_tool(name="git_status", arguments={})
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        sp = TypeAdapter(StatusPage).validate_python(payload)
        assert isinstance(sp.entries, list)


@pytest.mark.asyncio
async def test_git_log_oneline_basic(git_ro_session) -> None:
    async with git_ro_session() as session:
        res = await session.call_tool(
            name="git_log",
            arguments={
                "payload": LogInput(
                    rev="HEAD",
                    max_count=5,
                    oneline=True,
                    slice=TextSlice(offset_chars=0, max_chars=1000),
                ),
            },
        )
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        tp = TypeAdapter(TextPage).validate_python(payload)
        assert isinstance(tp.body, str)
