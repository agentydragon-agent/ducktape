from __future__ import annotations

from typing import Any

import pytest
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.inproc import fastmcp_inproc_client
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager, ServerSlot, session_opener


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **kwargs: Any) -> Response:  # type: ignore[override]
        self.calls += 1
        # First call: request to read the container.info resource via built-in tool
        if self.calls == 1:
            tc = ResponseFunctionToolCall(
                type="function_call",
                id="tc1",
                call_id="call-1",
                name="mcp__resources__read",
                arguments='{"server":"docker","uri":"resource://container.info","max_bytes":1024}',
            )
            return Response(
                id="r1",
                created_at=0,
                model="gpt-5.1-mini",
                object="response",
                output=[tc],
                parallel_tool_calls=False,
                tool_choice="auto",
                tools=[],
            )
        # Second call: assistant final text
        msg = ResponseOutputMessage(
            id="m1",
            type="message",
            role="assistant",
            status="completed",
            content=[ResponseOutputText(type="output_text", text="ok", annotations=[])],
        )
        return Response(
            id="r2",
            created_at=1,
            model="gpt-5.1-mini",
            object="response",
            output=[msg],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_model_reads_container_info_with_stubbed_openai() -> None:
    # Build in-proc FastMCP server slot named 'docker'
    def _cm_builder():
        return fastmcp_inproc_client(lambda: make_container_exec_mcp(image="alpine:3.19", describe=False))

    slots = {"docker": ServerSlot(name="docker", open_fn=session_opener(_cm_builder))}

    async with McpManager(slots) as mcp:
        client = FakeOpenAIClient()
        agent = await MiniCodex.create(
            model="gpt-5.1-mini",
            mcp=mcp,
            client=client,  # type: ignore[arg-type]
            system="test",
        )

        res = await agent.run("read container info", require_at_least_one_tool=True)
        kinds = [e.get("kind") for e in res.sequence]
        assert "tool_call" in kinds, f"no tool_call in sequence: {kinds}"
        assert "function_call_output" in kinds, f"no function_call_output in sequence: {kinds}"
        assert client.responses.calls == 2
