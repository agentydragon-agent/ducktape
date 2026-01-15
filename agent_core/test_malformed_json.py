"""Test agent's handling of malformed JSON in tool call arguments."""

from __future__ import annotations

from collections.abc import Callable

from hamcrest import all_of, assert_that, contains_string

from agent_core.agent import Agent
from agent_core.events import ToolCallOutput
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.matchers import tool_call_with_error_text
from agent_core_testing.openai_mock import make_mock
from agent_core_testing.responses import ResponsesFactory
from openai_utils.model import FunctionCallItem, ResponsesRequest, ResponsesResult, UserMessage


async def _run_malformed_json_test(
    mcp_client_echo,
    recording_handler,
    make_first_turn: Callable[[ResponsesFactory], ResponsesResult],
    parallel: bool = False,
) -> tuple[str, list]:
    """Helper to run malformed JSON tests with custom first turn."""
    factory = ResponsesFactory("test-model")

    async def handle_request(req: ResponsesRequest) -> ResponsesResult:
        if len(req.input) == 1:
            return make_first_turn(factory)
        return factory.make_assistant_message("I received an error")

    client = make_mock(handle_request)
    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=client,
        handlers=[FinishOnTextMessageHandler(), recording_handler],
        parallel_tool_calls=parallel,
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(UserMessage.text("use echo"))

    res = await agent.run()
    events = recording_handler.records
    return res.text, events


async def test_malformed_json_in_tool_arguments(mcp_client_echo, recording_handler) -> None:
    """Test that malformed JSON in tool arguments is converted to error tool result."""

    def make_turn(factory: ResponsesFactory) -> ResponsesResult:
        malformed_call = FunctionCallItem(
            type="function_call",
            name="echo_echo",
            arguments='{"text": "unterminated string',  # Malformed JSON
            call_id="test:1",
        )
        return factory.make(malformed_call)

    text, events = await _run_malformed_json_test(mcp_client_echo, recording_handler, make_turn)

    # Agent should complete successfully despite malformed JSON
    assert "error" in text.lower() or "invalid" in text.lower()

    # Check that error was emitted as a tool result
    tool_outputs = [evt for evt in events if isinstance(evt, ToolCallOutput)]
    assert len(tool_outputs) == 1

    tool_result = tool_outputs[0].result
    assert_that(
        tool_result,
        tool_call_with_error_text(all_of(contains_string("Invalid JSON"), contains_string("unterminated string"))),
    )


async def test_non_dict_json_in_tool_arguments(mcp_client_echo, recording_handler) -> None:
    """Test that non-dict JSON (like array) in tool arguments is converted to error."""

    def make_turn(factory: ResponsesFactory) -> ResponsesResult:
        non_dict_call = FunctionCallItem(
            type="function_call",
            name="echo_echo",
            arguments='["not", "an", "object"]',  # Valid JSON but not a dict
            call_id="test:1",
        )
        return factory.make(non_dict_call)

    text, events = await _run_malformed_json_test(mcp_client_echo, recording_handler, make_turn)

    # Agent should complete successfully
    assert "error" in text.lower()

    # Check that error was emitted as a tool result
    tool_outputs = [evt for evt in events if isinstance(evt, ToolCallOutput)]
    assert len(tool_outputs) == 1

    tool_result = tool_outputs[0].result
    assert_that(tool_result, tool_call_with_error_text(contains_string("must be a JSON object")))


async def test_malformed_json_parallel_tool_calls(mcp_client_echo, recording_handler) -> None:
    """Test malformed JSON handling with parallel tool calls enabled."""

    def make_turn(factory: ResponsesFactory) -> ResponsesResult:
        good_call = FunctionCallItem(
            type="function_call", name="echo_echo", arguments='{"text": "good call"}', call_id="test:1"
        )
        bad_call = FunctionCallItem(
            type="function_call",
            name="echo_echo",
            arguments='{"text": "bad',  # Malformed
            call_id="test:2",
        )
        return factory.make(good_call, bad_call)

    text, events = await _run_malformed_json_test(mcp_client_echo, recording_handler, make_turn, parallel=True)

    # Agent should complete successfully
    assert text

    # Check that we got two tool results: one success, one error
    tool_outputs = [evt for evt in events if isinstance(evt, ToolCallOutput)]
    assert len(tool_outputs) == 2

    # One should be error, one should be success
    results = [out.result for out in tool_outputs]
    error_count = sum(1 for r in results if r.isError)
    success_count = sum(1 for r in results if not r.isError)

    assert error_count == 1
    assert success_count == 1
