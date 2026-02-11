import pytest

from adgn.agent.loop_control import NoAction
from adgn.agent.reducer import BaseHandler, Reducer


class BadHandler(BaseHandler):
    def on_before_sample(self):
        return None  # invalid by policy


def test_all_defer_returns_continue():
    """All handlers deferring should result in NoAction() as default."""
    ctrl = Reducer([BaseHandler()])
    res = ctrl.on_before_sample()
    assert isinstance(res, NoAction)


def test_multiple_continue_passes_through():
    """Multiple NoAction() handlers should result in NoAction() (no merging, just pass-through)."""
    ctrl = Reducer([BaseHandler(), BaseHandler()])
    res = ctrl.on_before_sample()
    assert isinstance(res, NoAction)


def test_invalid_return_type_raises_type_error():
    """Invalid return type should raise TypeError."""
    ctrl = Reducer([BadHandler()])
    with pytest.raises(TypeError, match="invalid decision type"):
        ctrl.on_before_sample()
