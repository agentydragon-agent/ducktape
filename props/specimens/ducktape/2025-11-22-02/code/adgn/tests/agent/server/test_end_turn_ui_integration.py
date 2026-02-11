"""Test end_turn UI integration - ensures tool doesn't double-emit and renders as thick HR."""

from fastmcp.client.client import CallToolResult
from hamcrest import assert_that, has_length, instance_of

from adgn.agent.server.bus import ServerBus, UiEndTurn
from adgn.agent.server.protocol import FunctionCallOutput, ToolCall, UiEndTurnEvt
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import new_state
from adgn.mcp._shared.calltool import convert_fastmcp_result
from adgn.mcp._shared.naming import build_mcp_function


def test_end_turn_tool_filtering():
    """end_turn tool calls should not create Tool items in UI state."""
    state = new_state()

    # ToolCall for end_turn should be filtered out
    tool_call = ToolCall(name=build_mcp_function("ui", "end_turn"), call_id="test-123")
    after_call = reduce_ui_state(state, tool_call)

    # Function output for end_turn should also be filtered out
    output = FunctionCallOutput(
        call_id="test-123",
        result=convert_fastmcp_result(CallToolResult(content=[], structured_content={"ok": True}, is_error=False)),
    )
    after_output = reduce_ui_state(after_call, output)

    assert_that(after_call.items, has_length(0), "end_turn tool call should not create UI items")
    assert_that(after_output.items, has_length(0), "end_turn tool output should not create UI items")


def test_end_turn_event_creates_separator():
    """UiEndTurnEvt should create EndTurn items that render as thick HR."""
    state = new_state()

    # UiEndTurnEvt should create an EndTurn item
    evt = UiEndTurnEvt()
    new_state_obj = reduce_ui_state(state, evt)

    assert_that(new_state_obj.items, has_length(1), "UiEndTurnEvt should create one item")
    assert new_state_obj.items[0].kind == "EndTurn", "Should create EndTurn item"


def test_ui_bus_end_turn_flow():
    """UiBus.push_end_turn should create UiEndTurn item."""
    bus = ServerBus()

    bus.push_end_turn()
    messages = bus.drain_messages()

    assert_that(messages, has_length(1), "push_end_turn should create one message")
    assert_that(messages[0], instance_of(UiEndTurn))
    assert messages[0].kind == "EndTurn", "UiEndTurn should have EndTurn kind"


def test_ui_send_message_still_filtered():
    """send_message tool should still be filtered (regression test)."""
    state = new_state()

    # Both tools should be filtered
    send_msg_call = ToolCall(name=build_mcp_function("ui", "send_message"), call_id="msg-123")
    end_turn_call = ToolCall(name=build_mcp_function("ui", "end_turn"), call_id="end-123")

    after_send = reduce_ui_state(state, send_msg_call)
    after_end = reduce_ui_state(after_send, end_turn_call)

    assert_that(after_send.items, has_length(0), "send_message should still be filtered")
    assert_that(after_end.items, has_length(0), "end_turn should also be filtered")


def test_regular_tools_not_affected():
    """Regular tools should still create Tool items."""
    state = new_state()

    # Regular tool should create a Tool item
    regular_call = ToolCall(name=build_mcp_function("echo", "echo"), call_id="echo-123", args_json='{"text": "test"}')
    after_regular = reduce_ui_state(state, regular_call)

    assert_that(after_regular.items, has_length(1), "Regular tools should create items")
    assert after_regular.items[0].kind == "Tool", "Should create Tool item"
    assert after_regular.items[0].tool == build_mcp_function("echo", "echo"), "Should preserve tool name"
