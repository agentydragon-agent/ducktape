import pytest

from adgn.llm.mini_codex.aggregating_handler import (
    AggregatingController,
    BaseHandler,
    NoLoopDecision,
)
from adgn.llm.mini_codex.loop_control import Auto, Continue, RequireAny


class DeferringHandler(BaseHandler):
    def on_before_sample(self):
        return NoLoopDecision()


class DecisionHandlerA(BaseHandler):
    def on_before_sample(self):
        return Continue(RequireAny())


class DecisionHandlerB(BaseHandler):
    def on_before_sample(self):
        return Continue(Auto())


class BadHandler(BaseHandler):
    def on_before_sample(self):
        return None  # invalid by policy


def test_crash_on_no_decision():
    ctrl = AggregatingController([DeferringHandler()])
    with pytest.raises(RuntimeError):
        ctrl.on_before_sample()


def test_crash_on_conflicting_decisions():
    ctrl = AggregatingController([DecisionHandlerA(), DecisionHandlerB()])
    with pytest.raises(RuntimeError):
        ctrl.on_before_sample()


def test_agreeing_decisions_ok():
    # Two handlers that return equivalent LoopDecision values should succeed
    ctrl = AggregatingController([DecisionHandlerA(), DecisionHandlerA()])
    res = ctrl.on_before_sample()
    assert isinstance(res, Continue)


def test_invalid_return_type_raises_type_error():
    ctrl = AggregatingController([BadHandler()])
    with pytest.raises(TypeError):
        ctrl.on_before_sample()
