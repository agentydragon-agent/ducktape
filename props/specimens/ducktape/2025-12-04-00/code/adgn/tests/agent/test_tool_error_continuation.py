"""Test that tool call errors don't abort the agent turn.

This test verifies that when a tool call returns an error (e.g., validation error),
the agent continues with the next phase instead of aborting the entire turn.
"""

from __future__ import annotations

from hamcrest import assert_that, contains_string

from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.testing.simple_servers import SendMessageInput
from tests.agent.test_matchers import assert_function_call_output_structured


async def test_tool_error_continues_turn(
    responses_factory, make_pg_client, validation_server, recording_handler, make_test_agent
) -> None:
    """Test that a tool validation error doesn't abort the turn.

    The agent should:
    1. Call the tool with wrong mime type (text/plain)
    2. Get a validation error
    3. Continue to the next phase
    4. Retry with correct mime type (text/markdown)
    5. Successfully complete
    """
    async with make_pg_client({"validator": validation_server}) as mcp_client:
        # Simulate the agent trying with wrong mime, then correcting itself
        seq = [
            # First attempt with wrong mime type
            responses_factory.make_mcp_tool_call(
                "validator", "send_message", SendMessageInput(mime="text/plain", content="Hello")
            ),
            # After error, agent retries with correct mime type
            responses_factory.make_mcp_tool_call(
                "validator", "send_message", SendMessageInput(mime="text/markdown", content="Hello")
            ),
            # Final message
            responses_factory.make_assistant_message("Successfully sent message"),
        ]

        agent, _ = await make_test_agent(
            mcp_client,
            seq,
            handlers=[recording_handler],
            system="You are a helpful assistant. Use the validator tools.",
            tool_policy=RequireAnyTool(),
        )

        result = await agent.run("Send a greeting")

    # Verify the sequence of events
    tool_calls = [evt for evt in recording_handler.records if evt.get("kind") == "tool_call"]
    outputs = [evt for evt in recording_handler.records if evt.get("kind") == "function_call_output"]

    # Should have 2 tool calls
    assert len(tool_calls) == 2, f"Expected 2 tool calls, got {len(tool_calls)}"

    # First call should fail with validation error
    first_output = outputs[0]
    assert first_output["result"].get("is_error") is True
    error_content = first_output["result"]["content"][0]["text"]
    # Hamcrest contains-string checks for clarity
    assert_that(error_content.lower(), contains_string("error"))
    assert "text/markdown" in error_content or "literal" in error_content.lower()

    # Second call should succeed
    second_output = outputs[1]
    assert second_output["result"].get("is_error") is False
    assert_function_call_output_structured([second_output], ok=True)

    # Final result should contain the success message
    assert_that(result.text, contains_string("Successfully sent message"))
