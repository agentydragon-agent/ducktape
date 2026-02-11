from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.resources.server import ResourcesReadArgs
from adgn.openai_utils.model import FunctionCallItem, FunctionCallOutputItem
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, MakeCall


@pytest.mark.requires_docker
async def test_model_reads_container_info_with_stubbed_openai(
    reasoning_model, docker_inproc_spec_alpine, make_pg_client, recording_handler, make_step_runner
) -> None:
    async with make_pg_client({"runtime": docker_inproc_spec_alpine}) as mcp_client:
        # Prepare a deterministic two-step sequence: function_call then final text
        runner = make_step_runner(
            steps=[
                MakeCall(
                    "resources",
                    "read",
                    ResourcesReadArgs(server="docker", uri="resource://container.info", max_bytes=1024),
                ),
                AssistantMessage("ok"),
            ]
        )
        client = make_mock(runner.handle_request_async)
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            client=client,
            system="test",
            handlers=[DisplayEventsHandler(), recording_handler],
            tool_policy=RequireAnyTool(),
        )

        await agent.run("read container info")
        kinds = [e.get("kind") for e in recording_handler.records]
        assert "tool_call" in kinds
        assert "function_call_output" in kinds
        assert len(client.captured) == 2
        # Verify that the second call included the function_call and function_call_output (stateless replay).
        second = client.captured[1]
        input_items = list(second.input or [])
        assert any(isinstance(it, FunctionCallItem) for it in input_items), (
            f"Expected FunctionCallItem in next-turn input: {input_items}"
        )
        assert any(isinstance(it, FunctionCallOutputItem) for it in input_items), (
            f"Expected FunctionCallOutputItem in next-turn input: {input_items}"
        )
