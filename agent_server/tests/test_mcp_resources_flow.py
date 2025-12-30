from __future__ import annotations

import pytest
from agent_core.agent import Agent
from agent_core.events import ToolCall, ToolCallOutput
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core.testing import AssistantMessage, CapturingOpenAIModel, MakeCall
from mcp_infra.display import DisplayEventsHandler
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.resources.server import ResourcesReadArgs
from openai_utils.model import FunctionCallItem, FunctionCallOutputItem, UserMessage


@pytest.mark.requires_docker
async def test_model_reads_container_info_with_stubbed_openai(
    reasoning_model, docker_exec_server_py312slim, compositor, compositor_client, recording_handler, make_step_runner
) -> None:
    """Test model reading container info resources without policy gateway."""
    # Mount runtime server and capture Mounted object
    mounted_runtime = await compositor.mount_inproc(MCPMountPrefix("runtime"), docker_exec_server_py312slim)

    # Get container info URI from server instance (convert to string)
    container_info_uri = str(docker_exec_server_py312slim.container_info_resource.uri)

    # Prepare a deterministic two-step sequence: function_call then final text
    runner = make_step_runner(
        steps=[
            MakeCall(
                MCPMountPrefix("resources"),
                "read",
                ResourcesReadArgs(
                    server=mounted_runtime.prefix, uri=container_info_uri, start_offset=0, max_bytes=1024
                ),
            ),
            AssistantMessage("ok"),
        ]
    )
    client = CapturingOpenAIModel(runner)
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=client,
        handlers=[FinishOnTextMessageHandler(), DisplayEventsHandler(), recording_handler],
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(UserMessage.text("read container info"))

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
