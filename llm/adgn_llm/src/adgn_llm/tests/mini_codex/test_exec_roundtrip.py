from __future__ import annotations

import os
import pytest
from typing import AsyncIterator

from adgn_llm.mcp.inproc import fastmcp_inproc_client
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mini_codex.mcp_manager import McpManager, ServerSlot, session_opener
from mcp import types as mcp_types

ECHO_CMD = ["sh", "-lc", "printf hello"]


def _build_slots() -> dict[str, ServerSlot]:
    def _cm_builder():
        return fastmcp_inproc_client(
            lambda: make_container_exec_mcp(
                image="python:3.12-slim",
                working_dir="/workspace",
                volumes=None,
                describe=False,
            )
        )

    open_fn = session_opener(_cm_builder)
    return {"docker": ServerSlot(name="docker", open_fn=open_fn)}


async def _assert_exec_echo(mcp: McpManager) -> None:
    sess = await mcp.get_session("docker")
    res = await sess.call_tool(name="exec", arguments={"cmd": ECHO_CMD})
    assert isinstance(res, mcp_types.CallToolResult)
    sc = res.structuredContent
    assert isinstance(sc, dict)
    data = sc["result"] if "result" in sc else sc
    assert data["exit_code"] == 0
    assert (data["stdout"] or "") == "hello"
    assert (data.get("stderr") or "") == ""


@pytest.mark.asyncio
async def test_exec_roundtrip_echo() -> None:
    """Spin up real Docker container and roundtrip an echo via exec."""
    async with McpManager(_build_slots()) as mcp:
        await _assert_exec_echo(mcp)


@pytest.mark.live_llm
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="Requires OpenAI API key")
@pytest.mark.asyncio
async def test_live_llm_exec_echo() -> None:
    """End-to-end: real LLM is instructed to call docker exec to print hello and return exactly it."""
    from adgn_llm.mini_codex.agent import MiniCodex, _openai_client  # lazy import

    async with McpManager(_build_slots()) as mcp:
        client = _openai_client()
        agent = await MiniCodex.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-5"),
            mcp=mcp,
            system=(
                "You are testing an MCP exec tool.\n"
                f"Call the tool mcp__docker__exec with cmd={ECHO_CMD!r} and return exactly the stdout."
            ),
            client=client,
        )
        res = await agent.run("Run the command now and output exactly the stdout value.")
        text = (res.text or "").strip()
        assert text == "hello"
