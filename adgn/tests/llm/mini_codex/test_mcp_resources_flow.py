from __future__ import annotations

import json

import pytest
from adgn.llm.openai_utils.model import (
    ResponsesResult,
    Usage,
    FunctionCallOut,
    AssistantResponseMessage,
    FakeOpenAIModel,
)

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.resources.server import ResourcesReadArgs


@pytest.mark.asyncio
async def test_model_reads_container_info_with_stubbed_openai(
    reasoning_model,
    responses_factory,
    docker_inproc_spec_alpine,
) -> None:
    # Use shared in-proc FastMCP spec named 'docker' for Alpine image
    spec = docker_inproc_spec_alpine

    async with McpManager({"docker": spec}) as mcp:
        # Prepare a deterministic two-step sequence: function_call then final text
        args = ResourcesReadArgs(
            server="docker", uri="resource://container.info", max_bytes=1024
        )
        seq = [
            ResponsesResult(
                id="fc",
                usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
                output=[
                    FunctionCallOut(
                        call_id="call_1",
                        name="mcp__resources__read",
                        arguments=json.dumps(
                            {
                                "server": "docker",
                                "uri": "resource://container.info",
                                "start_offset": 0,
                                "max_bytes": 1024,
                            }
                        ),
                    )
                ],
            ),
            ResponsesResult(
                id="msg",
                usage=Usage(input_tokens=0, output_tokens=1, total_tokens=1),
                output=[AssistantResponseMessage(text="ok")],
            ),
        ]
        client = FakeOpenAIModel(seq)
        rec = RecordingHandler()  # from adgn.llm.mini_codex.loggers
        agent = await MiniCodex.create(
            model=reasoning_model,
            mcp=mcp,
            client=client,
            system="test",
            handlers=[AutoHandler(), DisplayEventsHandler(), rec],
        )

        await agent.run("read container info")
        kinds = [e.get("kind") for e in rec.records]
        assert "tool_call" in kinds
        assert "function_call_output" in kinds
        assert client.calls == 2
        # Verify that the second call included the function_call and function_call_output (stateless replay).
        second = client.captured[1]
        input_items = list(second.input or [])
        from adgn.llm.openai_utils.model import FunctionCallItem, FunctionCallOutputItem

        assert any(isinstance(it, FunctionCallItem) for it in input_items), (
            f"Expected FunctionCallItem in next-turn input: {input_items}"
        )
        assert any(isinstance(it, FunctionCallOutputItem) for it in input_items), (
            f"Expected FunctionCallOutputItem in next-turn input: {input_items}"
        )
