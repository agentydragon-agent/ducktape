"""Test that tool call errors don't abort the agent turn.

This test verifies that when a tool call returns an error (e.g., validation error),
the agent continues with the next phase instead of aborting the entire turn.
"""

from __future__ import annotations

from hamcrest import assert_that, contains_string, has_entries

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.matchers import assert_function_call_output_structured
from agent_core_testing.responses import DecoratorMock
from mcp_infra.naming import build_mcp_function
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.testing.simple_servers import SendMessageInput
from openai_utils.model import UserMessage


async def test_tool_error_continues_turn(compositor, compositor_client, validation_server, recording_handler) -> None:
    """Test that a tool validation error doesn't abort the turn.

    The agent should:
    1. Call the tool with wrong mime type (text/plain)
    2. Get a validation error
    3. Continue to the next phase
    4. Retry with correct mime type (text/markdown)
    5. Successfully complete
    """
    mounted = await compositor.mount_inproc(MCPMountPrefix("validator"), validation_server)
    tool_name = build_mcp_function(mounted.prefix, mounted.server.send_message_tool.name)

    @DecoratorMock.mock()
    def mock(m: DecoratorMock):
        yield
        # First attempt with wrong mime type
        yield m.tool_call(tool_name, SendMessageInput(mime="text/plain", content="Hello"))
        # After error, agent retries with correct mime type
        yield m.tool_call(tool_name, SendMessageInput(mime="text/markdown", content="Hello"))
        yield m.assistant_text("Successfully sent message")

    agent = await Agent.create(
        mcp_client=compositor_client,
        client=mock,
        handlers=[FinishOnTextMessageHandler(), recording_handler],
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(UserMessage.text("send message"))

    result = await agent.run()

    # Verify the sequence of events
    tool_calls = [evt for evt in recording_handler.records if evt.type == "tool_call"]
    outputs = [evt for evt in recording_handler.records if evt.type == "function_call_output"]

    assert len(tool_calls) == 2, f"Expected 2 tool calls, got {len(tool_calls)}"

    # First call should fail with validation error
    first_output = outputs[0]
    assert first_output.result.isError is True
    error_content = first_output.result.content[0].text
    assert_that(error_content.lower(), contains_string("error"))
    assert "text/markdown" in error_content or "literal" in error_content.lower()

    # Second call should succeed
    second_output = outputs[1]
    assert second_output.result.isError is False
    assert_function_call_output_structured([second_output], has_entries(ok=True))

    assert_that(result.text, contains_string("Successfully sent message"))
