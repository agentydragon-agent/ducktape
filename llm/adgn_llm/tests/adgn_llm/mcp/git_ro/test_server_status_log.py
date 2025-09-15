from __future__ import annotations

import json
import pytest
from pydantic import TypeAdapter

from adgn_llm.mini_codex.mcp_manager import build_mcp_function
from adgn_llm.mcp.git_ro.server import (
    TextPage,
    StatusPage,
    TextSlice,
    LogInput,
    GIT_RO_SERVER_NAME,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.git_ro.server import make_git_ro_server


@pytest.mark.asyncio
async def test_git_status_basic(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        name = build_mcp_function(GIT_RO_SERVER_NAME, "git_status")
        _server, tool = m.resolve_function(name)
        res = await sess.call_tool(name=tool, arguments={})
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        sp = TypeAdapter(StatusPage).validate_python(payload)
        assert isinstance(sp.entries, list)


@pytest.mark.asyncio
async def test_git_log_oneline_basic(repo_git_ro) -> None:
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        name = build_mcp_function(GIT_RO_SERVER_NAME, "git_log")
        _server, tool = m.resolve_function(name)
        res = await sess.call_tool(
            name=tool,
            arguments={
                "payload": LogInput(
                    rev="HEAD",
                    max_count=5,
                    oneline=True,
                    slice=TextSlice(offset_chars=0, max_chars=1000),
                ).model_dump()
            },
        )
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        tp = TypeAdapter(TextPage).validate_python(payload)
        assert isinstance(tp.body, str)
