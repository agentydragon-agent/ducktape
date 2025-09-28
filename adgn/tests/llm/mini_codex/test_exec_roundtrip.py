from __future__ import annotations

import os
import pytest

from adgn.llm.mcp._shared.container_session import ContainerOptions
from adgn.llm.mcp.docker_exec.server import (
    SERVER_NAME as DOCKER_SERVER_NAME,
    TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME,
    make_container_exec_mcp,
)
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import AgentResult, MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn.llm.mcp.testing.typed_stubs import TypedClient
from adgn.llm.mcp._shared.types import ExecInput, ExecResult
from adgn.llm.client_factory import build_client

ECHO_CMD = ["sh", "-lc", "printf hello"]


def _build_specs():
    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            ContainerOptions(
                image="python:3.12-slim",
                working_dir="/workspace",
                volumes=None,
                describe=True,
            )
        ),
    )
    return {"docker": spec}


async def _assert_exec_echo(mcp: McpManager) -> None:
    sess = await mcp.get_session("docker")
    # Introspect the in-proc FastMCP server to get typed models
    typed = TypedClient.from_server(
        make_container_exec_mcp(ContainerOptions(image="python:3.12-slim")), sess
    )
    ExecArgs = typed.models["docker_exec"].Input or ExecInput
    ExecOut = typed.models["docker_exec"].Output or ExecResult
    res: ExecOut = await typed.docker_exec(ExecArgs(cmd=ECHO_CMD))
    assert res.exit_code == 0
    assert (res.stdout or "") == "hello"
    assert (res.stderr or "") == ""


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_exec_roundtrip_echo() -> None:
    """Spin up real Docker container and roundtrip an echo via exec."""
    async with McpManager(_build_specs()) as mcp:
        await _assert_exec_echo(mcp)


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="Requires OpenAI API key",
)
@pytest.mark.asyncio
async def test_live_llm_exec_echo() -> None:
    """End-to-end: real LLM is instructed to call docker exec to print hello and return exactly it."""

    async with McpManager(_build_specs()) as mcp:
        model_name = os.environ.get("OPENAI_MODEL", "gpt-5")
        client = build_client(model_name)
        agent = await MiniCodex.create(
            model=model_name,
            mcp=mcp,
            system=(
                "You are testing an MCP exec tool.\n"
                "Call the tool "
                f"{build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME)} "
                f"with cmd={ECHO_CMD!r} and return exactly the stdout."
            ),
            client=client,
            handlers=[AutoHandler()],
        )
        res: AgentResult = await agent.run(
            "Run the command now and output exactly the stdout value.",
        )
        text = (res.text or "").strip()
        assert text == "hello"
