from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loggers import RecordingHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler
from adgn.mcp.resources.server import ResourcesReadArgs
from adgn.openai_utils.model import (
    FakeOpenAIModel,
    FunctionCallItem,
    FunctionCallOutputItem,
)


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_model_reads_container_info_with_stubbed_openai(
    reasoning_model,
    responses_factory,
    docker_inproc_spec_alpine,
) -> None:
    # Use shared in-proc FastMCP spec named 'docker' for Alpine image
    spec = docker_inproc_spec_alpine

    async with McpManager({}) as mcp:
        await mcp.attach_server("docker", spec)
        # Prepare a deterministic two-step sequence: function_call then final text
        ResourcesReadArgs(server="docker", uri="resource://container.info", max_bytes=1024)
        seq = [
            responses_factory.make_tool_call(
                "mcp__resources__read",
                {
                    "server": "docker",
                    "uri": "resource://container.info",
                    "start_offset": 0,
                    "max_bytes": 1024,
                },
            ),
            responses_factory.make_assistant_message("ok"),
        ]
        client = FakeOpenAIModel(seq)
        rec = RecordingHandler()  # from adgn.agent.loggers
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
        assert any(isinstance(it, FunctionCallItem) for it in input_items), (
            f"Expected FunctionCallItem in next-turn input: {input_items}"
        )
        assert any(isinstance(it, FunctionCallOutputItem) for it in input_items), (
            f"Expected FunctionCallOutputItem in next-turn input: {input_items}"
        )
