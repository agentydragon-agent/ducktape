from __future__ import annotations

from adgn.agent.loop_control import Abort, InjectItems
from adgn.agent.reducer import BaseHandler, Reducer
from adgn.openai_utils.model import InputTextPart, UserMessage
from adgn.openai_utils.text_extraction import extract_input_text_content


class _InsertsHandler(BaseHandler):
    def __init__(self, msg_id: str) -> None:
        self._msg_id = msg_id

    def on_before_sample(self):
        # Insert as input message (user role)
        msg = UserMessage(role="user", content=[InputTextPart(text=f"payload:{self._msg_id}")])
        return InjectItems(items=(msg,))


class _AbortHandler(BaseHandler):
    def on_before_sample(self):
        return Abort()


def test_first_inject_wins():
    """First handler with an action wins; second handler is not consulted."""
    ctrl = Reducer([_InsertsHandler("m1"), _InsertsHandler("m2")])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, InjectItems)
    assert len(dec.items) == 1
    # Only first handler's message should be present
    texts = extract_input_text_content(dec.items)
    assert texts == ["payload:m1"]


def test_first_action_wins_abort():
    """First handler returning Abort wins; Continue handler is not consulted."""
    ctrl = Reducer([_AbortHandler(), BaseHandler()])
    assert isinstance(ctrl.on_before_sample(), Abort)
