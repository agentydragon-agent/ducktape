from __future__ import annotations

import json
from pathlib import Path

import pytest

from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.git_ro.server import (
    TextPage,
    StatusPage,
    TextSlice,
    StatusInput,
    LogInput,
    DiffInput,
    make_git_ro_server,
    GIT_RO_SERVER_NAME,
    DiffResult,
    PatchResult,
)


@pytest.mark.asyncio
async def test_status_and_log_basic(git_repo_factory, git_run) -> None:
    repo: Path = git_repo_factory("repo2")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)
    git_run(["git", "commit", "-m", "add a"], repo)

    spec = make_inproc_slot_spec(make_git_ro_server(repo))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        name = build_mcp_function(GIT_RO_SERVER_NAME, "git_status")
        server, tool = m.resolve_function(name)
        sess = await m.get_session(server)
        res = await sess.call_tool(name=tool, arguments={"payload": StatusInput(porcelain=True).model_dump()})
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        sp = StatusPage.model_validate(payload)
        assert isinstance(sp.entries, list)

        name = build_mcp_function(GIT_RO_SERVER_NAME, "git_log")
        server, tool = m.resolve_function(name)
        res = await sess.call_tool(
            name=tool,
            arguments={
                "payload": LogInput(
                    rev="HEAD", max_count=5, oneline=True, slice=TextSlice(offset_chars=0, max_chars=1000)
                ).model_dump()
            },
        )
        payload = res.structuredContent
        if isinstance(payload, str):
            payload = json.loads(payload)
        tp = TextPage.model_validate(payload)
        assert isinstance(tp.body, str)


@pytest.mark.asyncio
async def test_diff_pagination_large_output(git_repo_factory, git_run) -> None:
    repo: Path = git_repo_factory("repo3")
    big = repo / "big.txt"
    big.write_text("\n".join(f"line {i}" for i in range(20000)) + "\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)

    spec = make_inproc_slot_spec(make_git_ro_server(repo))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        name = build_mcp_function(GIT_RO_SERVER_NAME, "git_diff")
        server, tool = m.resolve_function(name)
        sess = await m.get_session(server)
        res1 = await sess.call_tool(
            name=tool,
            arguments={
                "payload": DiffInput(
                    staged=True, unified=0, slice=TextSlice(offset_chars=0, max_chars=2000)
                ).model_dump()
            },
        )
        payload1 = res1.structuredContent
        if isinstance(payload1, str):
            payload1 = json.loads(payload1)
        assert isinstance(payload1, dict) and "result" in payload1
        union1 = TypeAdapter(DiffResult).validate_python(payload1["result"])
        assert isinstance(union1, PatchResult)
        page1 = union1.result
        assert isinstance(page1, TextPage)
        assert page1.truncated is True
        assert isinstance(page1.next_offset, int) and page1.next_offset > 0
        next_offset = page1.next_offset

        res2 = await sess.call_tool(
            name=tool,
            arguments={
                "payload": DiffInput(
                    staged=True, unified=0, slice=TextSlice(offset_chars=next_offset or 0, max_chars=2000)
                ).model_dump()
            },
        )
        payload2 = res2.structuredContent
        if isinstance(payload2, str):
            payload2 = json.loads(payload2)
        assert isinstance(payload2, dict) and "result" in payload2
        union2 = TypeAdapter(DiffResult).validate_python(payload2["result"])
        assert isinstance(union2, PatchResult)
        page2 = union2.result
        assert isinstance(page2, TextPage)
        assert page2.total_chars == page1.total_chars
        assert page2.body != page1.body
