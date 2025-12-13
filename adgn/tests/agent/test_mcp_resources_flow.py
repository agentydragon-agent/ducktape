from __future__ import annotations

import pytest

from adgn.agent.agent import Agent
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.resources.server import ResourcesReadArgs
from adgn.openai_utils.model import FunctionCallItem, FunctionCallOutputItem, UserMessage
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, MakeCall


@pytest.mark.requires_docker
async def test_model_reads_container_info_with_stubbed_openai(
    reasoning_model, docker_exec_server_alpine, make_pg_client, recording_handler, make_step_runner
) -> None:
    async with make_pg_client({"runtime": docker_exec_server_alpine}) as mcp_client:
        # Get container info URI from server instance
        container_info_uri = docker_exec_server_alpine.container_info_resource.uri

        # Prepare a deterministic two-step sequence: function_call then final text
        runner = make_step_runner(
            steps=[
                MakeCall(
                    MCPMountPrefix("resources"),
                    "read",
                    ResourcesReadArgs(
                        server=ContainerExecServer.DOCKER_MOUNT_PREFIX,
                        uri=container_info_uri,
                        start_offset=0,
                        max_bytes=1024,
                    ),
                ),
                AssistantMessage("ok"),
            ]
        )
        client = make_mock(runner.handle_request_async)
        agent = await Agent.create(
            mcp_client=mcp_client,
            client=client,
            handlers=[DisplayEventsHandler(), recording_handler],
            tool_policy=RequireAnyTool(),
        )
        agent.insert_message(UserMessage.text("read container info"))

        await agent.run()
        types = [e.type for e in recording_handler.records if isinstance(e, ToolCall | ToolCallOutput)]
        assert "tool_call" in types
        assert "function_call_output" in types
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
