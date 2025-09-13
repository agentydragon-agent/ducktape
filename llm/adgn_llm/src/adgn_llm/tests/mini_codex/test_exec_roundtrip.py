from __future__ import annotations

import os
import pytest

from adgn_llm.mcp.docker_exec.server import (
    make_container_exec_mcp,
    SERVER_NAME as DOCKER_SERVER_NAME,
    TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mini_codex.agent import MiniCodex
from mcp import types as mcp_types

ECHO_CMD = ["sh", "-lc", "printf hello"]


def _build_specs():
    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            image="python:3.12-slim",
            working_dir="/workspace",
            volumes=None,
            describe=True,
        )
    )
    return {"docker": spec}


async def _assert_exec_echo(mcp: McpManager) -> None:
    sess = await mcp.get_session("docker")
    res = await sess.call_tool(name="docker_exec", arguments={"cmd": ECHO_CMD})
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
    async with McpManager(_build_specs()) as mcp:
        await _assert_exec_echo(mcp)


@pytest.mark.live_llm
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="Requires OpenAI API key")
@pytest.mark.asyncio
async def test_live_llm_exec_echo() -> None:
    """End-to-end: real LLM is instructed to call docker exec to print hello and return exactly it."""

    async with McpManager(_build_specs()) as mcp:
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        agent = await MiniCodex.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-5"),
            mcp=mcp,
            system=(
                "You are testing an MCP exec tool.\n"
                f"Call the tool {build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME)} with cmd={ECHO_CMD!r} and return exactly the stdout."
            ),
            client=client,
        )
        res = await agent.run("Run the command now and output exactly the stdout value.")
        text = (res.text or "").strip()
        assert text == "hello"
