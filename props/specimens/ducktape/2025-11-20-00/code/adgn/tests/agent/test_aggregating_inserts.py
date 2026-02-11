from __future__ import annotations

import pytest
from hamcrest import all_of, assert_that, has_length, has_properties, instance_of

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import Abort, Auto, Continue
from adgn.agent.reducer import BaseHandler, Reducer
from adgn.openai_utils.model import FunctionCallItem, InputTextPart, UserMessage
from tests.agent.helpers import extract_input_text_content


class _InsertsHandler(BaseHandler):
    def __init__(self, msg_id: str) -> None:
        self._msg_id = msg_id

    def on_before_sample(self):
        # Insert as input message (user role), not output message
        msg = UserMessage(role="user", content=[InputTextPart(text=f"payload:{self._msg_id}")])
        return Continue(Auto(), inserts_input=(msg,))


class _ContinueOnlyHandler(BaseHandler):
    def on_before_sample(self):
        return Continue(Auto())


class _AbortHandler(BaseHandler):
    def on_before_sample(self):
        return Abort()


def test_aggregating_merges_inserts_additively():
    ctrl = Reducer([_InsertsHandler("m1"), _InsertsHandler("m2")])
    dec = ctrl.on_before_sample()
    assert_that(
        dec,
        all_of(
            instance_of(Continue),
            has_properties(tool_policy=instance_of(Auto), inserts_input=has_length(2)),
        ),
    )
    # Extract texts from input messages and assert ordering
    texts = extract_input_text_content(dec.inserts_input)
    assert texts == ["payload:m1", "payload:m2"]


def test_aggregating_continue_and_abort_conflict():
    ctrl = Reducer([_ContinueOnlyHandler(), _AbortHandler()])
    with pytest.raises(RuntimeError):
        _ = ctrl.on_before_sample()


class _InvalidFunctionCallInjectHandler(BaseHandler):
    """Handler that incorrectly injects FunctionCallItem without skip_sampling=True."""

    def on_before_sample(self):
        fc = FunctionCallItem(name="test", call_id="test_call", arguments="{}")
        return Continue(Auto(), inserts_input=(fc,))  # Missing skip_sampling=True


async def test_function_call_inject_without_skip_sampling_raises(fake_openai_client_factory, make_compositor):
    """Verify runtime check prevents FunctionCallItem injection without skip_sampling=True."""
    async with make_compositor({}) as (mcp_client, _comp):
        agent = await MiniCodex.create(
            model="test",
            system="test",
            mcp_client=mcp_client,
            client=fake_openai_client_factory([]),
            handlers=[_InvalidFunctionCallInjectHandler()],
        )
        with pytest.raises(TypeError, match="FunctionCallItem requires skip_sampling=True"):
            await agent.run("test")
