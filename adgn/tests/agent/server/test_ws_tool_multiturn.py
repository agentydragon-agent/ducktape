from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from adgn.agent.server import protocol
from tests.agent.ws_helpers import (
    assert_payloads_have,
    has_finished_run,
    is_function_call_output,
    is_function_call_output_end_turn,
    is_ui_message,
)
from tests.llm.support.openai_mock import make_mock

Envelope = protocol.Envelope


class DummyClient:
    @property
    def responses(self):  # pragma: no cover
        raise AssertionError("responses.create should not be called directly in this test")


@pytest.mark.timeout(5)
def test_ws_tool_multiturn(
    responses_factory,
    make_echo_spec,
    ws_session,
) -> None:
    """WS multi-turn: user -> echo tool -> typed MCP result -> UI message."""

    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            return responses_factory.make_tool_call(
                "mcp__echo__echo", {"text": "hello"}, call_id="call_echo"
            )
        if step == 1:
            return responses_factory.make_tool_call(
                "mcp__ui__send_message",
                {"mime": "text/markdown", "content": "**hello**"},
                call_id="call_ui_msg",
            )
        return responses_factory.make_tool_call("mcp__ui__end_turn", {}, call_id="call_ui_end")

    client = make_mock(responses_create)

    specs = make_echo_spec()

    try:
        with ws_session(client, specs=specs, auto_approve=True) as (
            client_ws,
            ws,
            collect,
            agent_id,
        ):
            ws.send_json({"type": "send", "text": "use echo"})
            payloads = collect(limit=200)
            assert_payloads_have(
                payloads,
                is_function_call_output(call_id="call_echo", ok=True, echo="hello"),
                is_function_call_output(
                    call_id="call_ui_msg", mime="text/markdown", content="**hello**"
                ),
                is_function_call_output_end_turn(call_id="call_ui_end"),
                is_ui_message(content="**hello**", mime="text/markdown"),
                has_finished_run(),
            )
    except CancelledError:
        pass
