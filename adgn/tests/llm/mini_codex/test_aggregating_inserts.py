from __future__ import annotations

import pytest

from adgn.llm.mini_codex.aggregating_handler import AggregatingController, BaseHandler
from adgn.llm.mini_codex.loop_control import Abort, Auto, Continue


class _InsertsHandler(BaseHandler):
    def __init__(self, msg_id: str) -> None:
        self._msg_id = msg_id

    def on_before_sample(self):  # type: ignore[override]
        # Insert as input message (user role), not output message
        msg = {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": f"payload:{self._msg_id}"},
            ],
        }
        return Continue(Auto(), inserts=(msg,))


class _ContinueOnlyHandler(BaseHandler):
    def on_before_sample(self):  # type: ignore[override]
        return Continue(Auto())


class _AbortHandler(BaseHandler):
    def on_before_sample(self):  # type: ignore[override]
        return Abort()


def test_aggregating_merges_inserts_additively():
    ctrl = AggregatingController([_InsertsHandler("m1"), _InsertsHandler("m2")])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Continue)
    assert dec.tool_policy.__class__ is Auto
    assert len(dec.inserts) == 2
    # Extract texts from input messages and assert ordering
    texts: list[str] = []
    for item in dec.inserts:
        d = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        contents = d.get("content") or []
        texts.extend(
            [
                c.get("text")
                for c in contents
                if isinstance(c, dict)
                and c.get("type") == "input_text"
                and isinstance(c.get("text"), str)
            ]
        )
    assert texts == ["payload:m1", "payload:m2"]


def test_aggregating_continue_and_abort_conflict():
    ctrl = AggregatingController([_ContinueOnlyHandler(), _AbortHandler()])
    with pytest.raises(RuntimeError):
        _ = ctrl.on_before_sample()
