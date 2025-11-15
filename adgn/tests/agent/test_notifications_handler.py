from __future__ import annotations

from adgn.agent.loop_control import Auto, Continue
from adgn.agent.notifications.types import NotificationsBatch, ResourceUpdateEvent
from adgn.agent.reducer import NotificationsHandler
from tests.agent.helpers import extract_input_text_content, strip_system_notification_wrapper


class _FakeBuffer:
    def __init__(self) -> None:
        # New notifications types do not carry synthetic versions; only server+uri
        self._batch = NotificationsBatch(
            resources_updated=[
                ResourceUpdateEvent(server="git-ro", uri="http://a.txt"),
                ResourceUpdateEvent(server="editor", uri="file:///b.py"),
            ]
        )

    def poll(self) -> NotificationsBatch:
        b = self._batch
        # Return once, then empty
        self._batch = NotificationsBatch()
        return b


def test_notifications_handler_batches_single_message():
    buf = _FakeBuffer()
    h = NotificationsHandler(buf.poll)
    dec = h.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, Auto)
    assert len(dec.inserts_input) == 1
    msg = dec.inserts_input[0]
    # Extract input_text content from the message
    texts = extract_input_text_content([msg])
    assert texts, "expected an input_text content part"
    text = texts[0]
    # Strip system notification wrapper if present
    text = strip_system_notification_wrapper(text)
    # Simple repr-snippet assertion: ensure server names are present
    assert "git-ro" in text
    assert "editor" in text
    # Second call returns NoLoopDecision (empty)
    dec2 = h.on_before_sample()
    # NoLoopDecision has no attributes; assert by type name
    assert type(dec2).__name__ == "NoLoopDecision"
