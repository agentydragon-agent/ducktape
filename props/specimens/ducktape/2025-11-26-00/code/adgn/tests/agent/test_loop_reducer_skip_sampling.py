from __future__ import annotations

import pytest

from adgn.agent.loop_control import Auto, Continue
from adgn.agent.reducer import BaseHandler, Reducer


class _SkipHandler(BaseHandler):
    def __init__(self, *, skip: bool, inserts: tuple | None = None, policy: Auto | None = None) -> None:
        self._skip = skip
        self._inserts = inserts or ()
        self._policy = policy or Auto()

    def on_before_sample(self):
        return Continue(self._policy, inserts_input=self._inserts, skip_sampling=self._skip)


def test_all_continue_same_policy_skip_true_merge():
    m1 = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "a"}]}
    m2 = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "b"}]}
    ctrl = Reducer([_SkipHandler(skip=True, inserts=(m1,)), _SkipHandler(skip=True, inserts=(m2,))])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, Auto)
    assert getattr(dec, "skip_sampling", False) is True
    assert tuple(dec.inserts_input) == (m1, m2)


def test_all_continue_same_policy_no_skip_merge():
    m1 = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "x"}]}
    m2 = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "y"}]}
    ctrl = Reducer([_SkipHandler(skip=False, inserts=(m1,)), _SkipHandler(skip=False, inserts=(m2,))])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, Auto)
    assert getattr(dec, "skip_sampling", False) is False
    assert tuple(dec.inserts_input) == (m1, m2)


def test_mixed_skip_sampling_conflict_raises():
    ctrl = Reducer([_SkipHandler(skip=True), _SkipHandler(skip=False)])
    with pytest.raises(RuntimeError):
        _ = ctrl.on_before_sample()
