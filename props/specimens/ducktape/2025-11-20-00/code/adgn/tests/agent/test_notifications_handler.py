from __future__ import annotations

from hamcrest import all_of, assert_that, contains_string, has_length, has_properties, instance_of

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
    assert_that(
        dec,
        all_of(instance_of(Continue), has_properties(tool_policy=instance_of(Auto), inserts_input=has_length(1))),
    )
    msg = dec.inserts_input[0]
    # Extract input_text content from the message
    texts = extract_input_text_content([msg])
    assert texts, "expected an input_text content part"
    text = texts[0]
    # Strip system notification wrapper if present
    text = strip_system_notification_wrapper(text)
    # Simple repr-snippet assertion: ensure server names are present
    assert_that(text, all_of(contains_string("git-ro"), contains_string("editor")))
    # Second call returns NoLoopDecision (empty)
    dec2 = h.on_before_sample()
    # NoLoopDecision has no attributes; assert by type name
    assert type(dec2).__name__ == "NoLoopDecision"
