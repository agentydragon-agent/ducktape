from __future__ import annotations

from adgn.agent.reducer import NotificationsHandler
from adgn.agent.loop_control import Auto, Continue
from adgn.agent.mcp_manager import (
    McpManager,
    NotificationsBatch,
    ResourceUpdateEvent,
)


class _FakeMcp(McpManager):
    def __init__(self) -> None:
        super().__init__({})
        self._batch = NotificationsBatch(
            resources_updated=[
                ResourceUpdateEvent(server="git-ro", uri="http://a.txt", version=2),
                ResourceUpdateEvent(server="editor", uri="file:///b.py", version=1),
            ],
            tools_invalidated=[],
        )

    async def __aenter__(self) -> "_FakeMcp":  # pragma: no cover
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover
        return None

    def poll_notifications(self) -> NotificationsBatch:
        b = self._batch
        # Return once, then empty
        self._batch = NotificationsBatch()
        return b


def test_notifications_handler_batches_single_message():
    mcp = _FakeMcp()
    h = NotificationsHandler(mcp)
    dec = h.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, Auto)
    assert len(dec.inserts_input) == 1
    msg = dec.inserts_input[0]
    # Normalize to dict (some SDK items are Pydantic models)
    msgd = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else msg
    # Extract input_text content and parse payload (ignore role/type; we only care about content)
    contents = (msgd.get("content") or []) if isinstance(msgd, dict) else []
    texts = [
        c.get("text")
        for c in contents
        if isinstance(c, dict)
        and c.get("type") == "input_text"
        and isinstance(c.get("text"), str)
    ]
    assert texts, "expected an input_text content part"
    text = texts[0]
    if text.startswith("<system notification>\n") and text.endswith(
        "\n</system notification>"
    ):
        text = text[len("<system notification>\n") : -len("\n</system notification>")]
    # Simple repr-snippet assertion: ensure server names are present
    assert "git-ro" in text
    assert "editor" in text
    # Second call returns NoLoopDecision (empty)
    dec2 = h.on_before_sample()
    # NoLoopDecision has no attributes; assert by type name
    assert type(dec2).__name__ == "NoLoopDecision"
