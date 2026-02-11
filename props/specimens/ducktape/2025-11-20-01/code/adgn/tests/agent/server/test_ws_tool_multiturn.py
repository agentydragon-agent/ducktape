from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ws_helpers import (
    assert_payloads_have,
    has_finished_run,
    is_function_call_output,
    is_function_call_output_end_turn,
    is_ui_message,
)
from tests.llm.support.openai_mock import make_mock


@pytest.mark.timeout(15)
def test_ws_tool_multiturn(responses_factory, make_echo_spec, agent_ws_box) -> None:
    """WS multi-turn: user -> echo tool -> typed MCP result -> UI message."""

    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "hello"}, call_id="call_echo"
            )
        if step == 1:
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "send_message"),
                {"mime": "text/markdown", "content": "**hello**"},
                call_id="call_ui_msg",
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    client = make_mock(responses_create)

    specs = dict(make_echo_spec())

    try:
        with agent_ws_box(client, specs=specs, auto_approve=True) as box:
            # Use REST to kick off the run; WS will carry server events
            r = box.http.prompt("use echo")
            assert r.status_code == 200
            assert (r.json() or {}).get("ok") is True
            payloads = box.collect(limit=180)
            assert_payloads_have(
                payloads,
                is_function_call_output(call_id="call_echo", ok=True, echo="hello"),
                is_function_call_output(call_id="call_ui_msg", mime="text/markdown", content="**hello**"),
                is_function_call_output_end_turn(call_id="call_ui_end"),
                is_ui_message(content="**hello**", mime="text/markdown"),
                has_finished_run(),
            )
    except CancelledError:
        pass
