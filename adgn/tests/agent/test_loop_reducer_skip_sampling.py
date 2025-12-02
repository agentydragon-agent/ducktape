from __future__ import annotations

from adgn.agent.loop_control import Abort, Continue, InjectItems, NoLoopDecision
from adgn.agent.reducer import BaseHandler, Reducer
from adgn.openai_utils.model import InputTextPart, UserMessage


class _ContinueHandler(BaseHandler):
    def on_before_sample(self):
        return Continue()


class _InjectHandler(BaseHandler):
    def __init__(self, items: tuple) -> None:
        self._items = items

    def on_before_sample(self):
        return InjectItems(items=self._items)


class _AbortHandler(BaseHandler):
    def on_before_sample(self):
        return Abort()


class _DeferHandler(BaseHandler):
    def on_before_sample(self):
        return NoLoopDecision()


def test_first_action_wins_inject():
    """First handler with InjectItems wins; second handler not consulted."""
    msg = UserMessage(role="user", content=[InputTextPart(text="first")])
    ctrl = Reducer([_InjectHandler((msg,)), _ContinueHandler()])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, InjectItems)
    assert len(dec.items) == 1


def test_first_action_wins_abort():
    """First handler with Abort wins; second handler not consulted."""
    ctrl = Reducer([_AbortHandler(), _ContinueHandler()])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Abort)


def test_defer_passes_to_next_handler():
    """NoLoopDecision defers to next handler."""
    msg = UserMessage(role="user", content=[InputTextPart(text="deferred")])
    ctrl = Reducer([_DeferHandler(), _InjectHandler((msg,))])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, InjectItems)


def test_all_continue_returns_continue():
    """All handlers returning Continue results in Continue()."""
    ctrl = Reducer([_ContinueHandler(), _ContinueHandler()])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Continue)


def test_all_defer_returns_continue():
    """All handlers deferring results in Continue() as default."""
    ctrl = Reducer([_DeferHandler(), _DeferHandler()])
    dec = ctrl.on_before_sample()
    assert isinstance(dec, Continue)
