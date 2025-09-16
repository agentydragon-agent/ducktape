from __future__ import annotations

from typing import Any

import pytest
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import AutoHandler
from adgn_llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn_llm.mini_codex.loggers import RecordingHandler
from adgn_llm.mini_codex.mcp_manager import McpManager
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, model: str, **kwargs: Any) -> Response:  # type: ignore[override]
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
                model=model,
                object="response",
                output=[tc],
                parallel_tool_calls=False,
                tool_choice="auto",
                tools=[],
                usage=ResponseUsage(
                    input_tokens=0,
                    input_tokens_details=InputTokensDetails(cached_tokens=0),
                    output_tokens=0,
                    output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                    total_tokens=0,
                ),
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
            model=model,
            object="response",
            output=[msg],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=1,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=1,
            ),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_model_reads_container_info_with_stubbed_openai() -> None:
    # Build in-proc FastMCP server spec named 'docker'
    spec = make_inproc_slot_spec(make_container_exec_mcp(image="alpine:3.19", describe=False))

    async with McpManager({"docker": spec}) as mcp:
        client = FakeOpenAIClient()
        rec = RecordingHandler()  # from adgn_llm.mini_codex.loggers
        agent = await MiniCodex.create(
            model="gpt-4.1-mini",
            mcp=mcp,
            client=client,
            system="test",
            handlers=[AutoHandler(), DisplayEventsHandler(), rec],
        )

        await agent.run("read container info")
        kinds = [e.get("kind") for e in rec.records]
        assert "tool_call" in kinds
        assert "function_call_output" in kinds
        assert client.responses.calls == 2
