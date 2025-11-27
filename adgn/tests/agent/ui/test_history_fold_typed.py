from __future__ import annotations

from datetime import UTC, datetime

from fastmcp.client.client import CallToolResult

from adgn.agent.persist.events import EventRecord, FunctionCallOutputPayload, ToolCallPayload, UserTextPayload
from adgn.agent.server.history import fold_events_to_ui_state
from adgn.mcp._shared.calltool import to_pydantic
from adgn.mcp._shared.naming import build_mcp_function


def test_fold_events_typed_ui_message() -> None:
    now = datetime.now(UTC)
    # Simulate ui.send_message tool producing a CallToolResult with structured content
    result = to_pydantic(
        CallToolResult(
            content=[],
            is_error=False,
            structured_content={"kind": "UiMessage", "mime": "text/markdown", "content": "**hello**"},
            meta=None,
        )
    )

    events = [
        EventRecord(seq=1, ts=now, payload=UserTextPayload(text="hi")),
        EventRecord(
            seq=2,
            ts=now,
            payload=ToolCallPayload(name=build_mcp_function("ui", "send_message"), args_json=None, call_id="c1"),
            call_id="c1",
        ),
        EventRecord(
            seq=3,
            ts=now,
            payload=FunctionCallOutputPayload(call_id="c1", result=result),
            call_id="c1",
        ),
    ]

    state = fold_events_to_ui_state(events)
    # Expect 2 UI items: user message and assistant markdown
    assert state.items[0].kind == "UserMessage"
    assert state.items[1].kind == "AssistantMarkdown"
    assert getattr(state.items[1], "md", "") == "**hello**"
