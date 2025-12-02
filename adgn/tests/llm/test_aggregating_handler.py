import pytest

from adgn.agent.loop_control import Continue, NoLoopDecision
from adgn.agent.reducer import BaseHandler, Reducer


class DeferringHandler(BaseHandler):
    def on_before_sample(self):
        return NoLoopDecision()


class ContinueHandler(BaseHandler):
    def on_before_sample(self):
        return Continue()


class BadHandler(BaseHandler):
    def on_before_sample(self):
        return None  # invalid by policy


def test_all_defer_returns_continue():
    """All handlers deferring should result in Continue() as default."""
    ctrl = Reducer([DeferringHandler()])
    res = ctrl.on_before_sample()
    assert isinstance(res, Continue)


def test_multiple_continue_passes_through():
    """Multiple Continue() handlers should result in Continue() (no merging, just pass-through)."""
    ctrl = Reducer([ContinueHandler(), ContinueHandler()])
    res = ctrl.on_before_sample()
    assert isinstance(res, Continue)


def test_invalid_return_type_raises_type_error():
    """Invalid return type should raise TypeError."""
    ctrl = Reducer([BadHandler()])
    with pytest.raises(TypeError, match="invalid decision type"):
        ctrl.on_before_sample()
