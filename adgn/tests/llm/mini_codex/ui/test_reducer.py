from __future__ import annotations

import json

from mcp import types as mcp_types

from adgn.llm.mini_codex.ui.reducer import reduce_ui_state
from adgn.llm.mini_codex.ui.state import UiState, new_state
from adgn.llm.mini_codex.ui.protocol import (
    UserText,
    ToolCall,
    FunctionCallOutput,
    ApprovalDecisionEvt,
    ApprovalApprove,
    UiMessageEvt,
    UiMessagePayload,
)


def test_user_text_appends_user_message():
    s: UiState = new_state()
    s2 = reduce_ui_state(s, UserText(text="hello"))
    assert s2.seq == 1
    assert len(s2.items) == 1
    it = s2.items[0]
    assert it.kind == "UserMessage"
    assert it.text == "hello"


def test_tool_call_exec_starts_exec_content_with_cmd():
    s = new_state()
    args = {"argv": ["echo", "hi there"]}
    s2 = reduce_ui_state(
        s,
        ToolCall(
            name="mcp__seatbelt__sandbox_exec", args_json=json.dumps(args), call_id="c1"
        ),
    )
    assert s2.seq == 1
    assert len(s2.items) == 1
    it = s2.items[0]
    assert it.kind == "Tool"
    assert it.tool == "mcp__seatbelt__sandbox_exec"
    assert it.call_id == "c1"
    assert it.decision is None
    assert it.content.content_kind == "Exec"
    # command assembled with conservative quoting
    assert it.content.cmd.startswith("echo ")


def test_tool_call_json_starts_json_content_with_args():
    s = new_state()
    args = {"foo": 1, "bar": "baz"}
    s2 = reduce_ui_state(
        s, ToolCall(name="mcp__demo__inspect", args_json=json.dumps(args), call_id="c2")
    )
    assert s2.seq == 1
    it = s2.items[0]
    assert it.kind == "Tool"
    assert it.content.content_kind == "Json"
    assert it.content.args == args


def test_approval_sets_single_decision():
    s = new_state()
    s1 = reduce_ui_state(
        s, ToolCall(name="mcp__ui__noop", args_json="{}", call_id="c3")
    )
    s2 = reduce_ui_state(
        s1, ApprovalDecisionEvt(call_id="c3", decision=ApprovalApprove())
    )
    it = s2.items[0]
    assert it.kind == "Tool"
    assert it.decision == "approve"


def test_function_output_updates_exec_stream():
    s = new_state()
    s1 = reduce_ui_state(
        s,
        ToolCall(
            name="mcp__seatbelt__sandbox_exec",
            args_json=json.dumps({"argv": ["ls"]}),
            call_id="c4",
        ),
    )
    result = mcp_types.CallToolResult(
        content=[],
        structuredContent={"stdout": "ok", "stderr": "", "exit_code": 0},
        isError=False,
    )
    s2 = reduce_ui_state(
        s1,
        FunctionCallOutput(
            call_id="c4", result=result.model_dump(mode="json", exclude_none=True)
        ),
    )
    it = s2.items[0]
    assert it.kind == "Tool"
    assert it.content.content_kind == "Exec"
    assert it.content.stdout == "ok"
    assert it.content.exit_code == 0


def test_function_output_updates_json_output_when_not_exec():
    s = new_state()
    s1 = reduce_ui_state(
        s,
        ToolCall(name="mcp__kv__get", args_json=json.dumps({"key": "k"}), call_id="c5"),
    )
    payload = {"value": {"a": 1}}
    result = mcp_types.CallToolResult(
        content=[], structuredContent=payload, isError=False
    ).model_dump(mode="json", exclude_none=True)
    s2 = reduce_ui_state(s1, FunctionCallOutput(call_id="c5", result=result))
    it = s2.items[0]
    assert it.kind == "Tool"
    assert it.content.content_kind == "Json"
    assert it.content.result == result


def test_ui_message_becomes_assistant_markdown():
    s = new_state()
    s2 = reduce_ui_state(
        s,
        UiMessageEvt(message=UiMessagePayload(mime="text/markdown", content="**hi**")),
    )
    assert s2.seq == 1
    it = s2.items[0]
    assert it.kind == "AssistantMarkdown"
    assert it.md == "**hi**"
