from __future__ import annotations

from datetime import datetime, timezone

from fastmcp.client.client import CallToolResult as FMCallToolResult

from adgn.agent.persist import EventType
from adgn.agent.persist.events import (
    EventRecord,
    FunctionCallOutputPayload,
    ToolCallPayload,
    UserTextPayload,
)
from adgn.agent.server.history import fold_events_to_ui_state


def test_fold_events_typed_ui_message() -> None:
    now = datetime.now(timezone.utc)
    # Simulate ui.send_message tool producing a CallToolResult with structured content
    result = FMCallToolResult(
        content=[],
        is_error=False,
        structured_content={"mime": "text/markdown", "content": "**hello**"},
    )

    events = [
        EventRecord(seq=1, ts=now, type=EventType.USER_TEXT, payload=UserTextPayload(text="hi")),
        EventRecord(
            seq=2,
            ts=now,
            type=EventType.TOOL_CALL,
            payload=ToolCallPayload(name="mcp__ui__send_message", args_json=None, call_id="c1"),
            call_id="c1",
        ),
        EventRecord(
            seq=3,
            ts=now,
            type=EventType.FUNCTION_CALL_OUTPUT,
            payload=FunctionCallOutputPayload(call_id="c1", result=result),
            call_id="c1",
        ),
    ]

    state = fold_events_to_ui_state(events)
    # Expect 2 UI items: user message and assistant markdown
    assert state.items[0].kind == "UserMessage"
    assert state.items[1].kind == "AssistantMarkdown"
    assert getattr(state.items[1], "md", "") == "**hello**"
