"""Test agent's handling of malformed JSON in tool call arguments."""

from __future__ import annotations

from collections.abc import Callable

from adgn.agent.agent import MiniCodex
from adgn.agent.events import ToolCallOutput
from adgn.agent.loop_control import RequireAnyTool
from adgn.openai_utils.model import FunctionCallItem, ResponsesRequest, ResponsesResult
from tests.llm.support.openai_mock import make_mock
from tests.support.responses import ResponsesFactory


async def _run_malformed_json_test(
    pg_client_echo,
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
    agent = await MiniCodex.create(
        mcp_client=pg_client_echo,
        system="test",
        client=client,
        handlers=[recording_handler],
        parallel_tool_calls=parallel,
        tool_policy=RequireAnyTool(),
    )

    res = await agent.run(user_text="use echo")
    events = recording_handler.records
    return res.text, events


async def test_malformed_json_in_tool_arguments(pg_client_echo, recording_handler) -> None:
    """Test that malformed JSON in tool arguments is converted to error tool result."""

    def make_turn(factory: ResponsesFactory) -> ResponsesResult:
        malformed_call = FunctionCallItem(
            type="function_call",
            name="echo_echo",
            arguments='{"text": "unterminated string',  # Malformed JSON
            call_id="test:1",
        )
        return factory.make(malformed_call)

    text, events = await _run_malformed_json_test(pg_client_echo, recording_handler, make_turn)

    # Agent should complete successfully despite malformed JSON
    assert "error" in text.lower() or "invalid" in text.lower()

    # Check that error was emitted as a tool result
    tool_outputs = [evt for evt in events if isinstance(evt, ToolCallOutput)]
    assert len(tool_outputs) == 1

    tool_result = tool_outputs[0].result
    assert tool_result.isError is True
    assert len(tool_result.content) > 0
    error_text = tool_result.content[0].text
    assert "Invalid JSON" in error_text
    assert "unterminated string" in error_text.lower()


async def test_non_dict_json_in_tool_arguments(pg_client_echo, recording_handler) -> None:
    """Test that non-dict JSON (like array) in tool arguments is converted to error."""

    def make_turn(factory: ResponsesFactory) -> ResponsesResult:
        non_dict_call = FunctionCallItem(
            type="function_call",
            name="echo_echo",
            arguments='["not", "an", "object"]',  # Valid JSON but not a dict
            call_id="test:1",
        )
        return factory.make(non_dict_call)

    text, events = await _run_malformed_json_test(pg_client_echo, recording_handler, make_turn)

    # Agent should complete successfully
    assert "error" in text.lower()

    # Check that error was emitted as a tool result
    tool_outputs = [evt for evt in events if isinstance(evt, ToolCallOutput)]
    assert len(tool_outputs) == 1

    tool_result = tool_outputs[0].result
    assert tool_result.isError is True
    error_text = tool_result.content[0].text
    assert "must be a JSON object" in error_text


async def test_malformed_json_parallel_tool_calls(pg_client_echo, recording_handler) -> None:
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

    text, events = await _run_malformed_json_test(pg_client_echo, recording_handler, make_turn, parallel=True)

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
