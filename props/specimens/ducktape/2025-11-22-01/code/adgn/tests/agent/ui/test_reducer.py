from __future__ import annotations

import json

from fastmcp.client.client import CallToolResult
from hamcrest import all_of, assert_that, has_properties, instance_of
from mcp import types

from adgn.agent.server.bus import MimeType
from adgn.agent.server.protocol import (
    ApprovalApprove,
    ApprovalDecisionEvt,
    FunctionCallOutput,
    ToolCall,
    UiMessageEvt,
    UiMessagePayload,
    UserText,
)
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state
from adgn.mcp._shared.calltool import convert_fastmcp_result
from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ui.typed_asserts import (
    assert_typed_items_have_one,
    is_assistant_markdown,
    is_exec_content_typed,
    is_tool_item,
    is_tool_item_typed,
    is_user_message,
)


def test_user_text_appends_user_message():
    s: UiState = new_state()
    s2 = reduce_ui_state(s, UserText(text="hello"))
    assert s2.seq == 1
    assert_typed_items_have_one(s2.items, is_user_message("hello"))


def test_tool_call_exec_starts_exec_content_with_cmd():
    s = new_state()
    args = {"argv": ["echo", "hi there"]}
    s2 = reduce_ui_state(
        s, ToolCall(name=build_mcp_function("seatbelt", "sandbox_exec"), args_json=json.dumps(args), call_id="c1")
    )
    assert s2.seq == 1
    assert_typed_items_have_one(
        s2.items, is_tool_item(tool=build_mcp_function("seatbelt", "sandbox_exec"), call_id="c1")
    )
    it = s2.items[0]
    assert_that(it, is_tool_item_typed(decision=None))
    assert_that(it.content, is_exec_content_typed(content_kind="Exec"))
    # command assembled with conservative quoting
    assert it.content.cmd is not None
    assert it.content.cmd.startswith("echo ")


def test_tool_call_json_starts_json_content_with_args():
    s = new_state()
    args = {"foo": 1, "bar": "baz"}
    s2 = reduce_ui_state(
        s, ToolCall(name=build_mcp_function("demo", "inspect"), args_json=json.dumps(args), call_id="c2")
    )
    assert s2.seq == 1
    assert_typed_items_have_one(s2.items, is_tool_item(call_id="c2"))
    it = s2.items[0]
    assert_that(it, is_tool_item_typed())
    assert_that(it.content, has_properties(content_kind="Json", args=args))


def test_approval_sets_single_decision():
    s = new_state()
    s1 = reduce_ui_state(s, ToolCall(name=build_mcp_function("ui", "noop"), args_json="{}", call_id="c3"))
    s2 = reduce_ui_state(s1, ApprovalDecisionEvt(call_id="c3", decision=ApprovalApprove()))
    it = s2.items[0]
    assert_that(it, is_tool_item_typed(kind="Tool", decision="approve"))


def test_function_output_updates_exec_stream():
    s = new_state()
    s1 = reduce_ui_state(
        s,
        ToolCall(
            name=build_mcp_function("seatbelt", "sandbox_exec"), args_json=json.dumps({"argv": ["ls"]}), call_id="c4"
        ),
    )
    result = CallToolResult(
        content=[], structured_content={"stdout": "ok", "stderr": "", "exit_code": 0}, is_error=False
    )
    pydantic_result = convert_fastmcp_result(result)
    s2 = reduce_ui_state(s1, FunctionCallOutput(call_id="c4", result=pydantic_result))
    it = s2.items[0]
    assert_that(it, is_tool_item_typed(kind="Tool"))
    assert_that(it.content, is_exec_content_typed(content_kind="Exec", stdout="ok", exit_code=0))


def test_function_output_updates_json_output_when_not_exec():
    s = new_state()
    s1 = reduce_ui_state(
        s, ToolCall(name=build_mcp_function("kv", "get"), args_json=json.dumps({"key": "k"}), call_id="c5")
    )
    payload = {"value": {"a": 1}}
    result = CallToolResult(content=[], structured_content=payload, is_error=False)
    pydantic_result = convert_fastmcp_result(result)
    s2 = reduce_ui_state(s1, FunctionCallOutput(call_id="c5", result=pydantic_result))
    it = s2.items[0]
    assert_that(it, is_tool_item_typed(kind="Tool"))
    assert_that(it.content, has_properties(content_kind="Json"))
    stored = it.content.result
    assert_that(stored, all_of(instance_of(types.CallToolResult), has_properties(structuredContent=payload)))


def test_ui_message_becomes_assistant_markdown():
    s = new_state()
    s2 = reduce_ui_state(s, UiMessageEvt(message=UiMessagePayload(mime=MimeType.MARKDOWN, content="**hi**")))
    assert s2.seq == 1
    assert_typed_items_have_one(s2.items, is_assistant_markdown("**hi**"))
