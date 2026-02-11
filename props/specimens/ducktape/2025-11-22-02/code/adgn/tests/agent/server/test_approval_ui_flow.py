"""Test that approval prompts auto-appear in UI without refresh."""

from __future__ import annotations

from concurrent.futures import CancelledError

from hamcrest import assert_that, has_items, has_properties
import pytest

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ws_helpers import has_finished_run, is_function_call_output_end_turn
from tests.llm.support.openai_mock import make_mock


@pytest.mark.timeout(10)
def test_approval_prompt_auto_appears(responses_factory, make_echo_spec, agent_ws_box) -> None:
    """Test that approval prompts appear immediately in UI without manual refresh."""

    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            # Agent tries to call echo tool - should trigger approval prompt
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "hello"}, call_id="call_echo"
            )
        # After approval, agent should end turn
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    client = make_mock(responses_create)
    specs = make_echo_spec()

    try:
        with agent_ws_box(client, specs=specs, auto_approve=True) as box:
            # Prompt via REST; UI approvals flow remains via WS events
            r = box.http.prompt("use echo tool to say hello")
            assert r.status_code == 200
            assert (r.json() or {}).get("ok") is True
            payloads = box.collect(limit=100)
            assert_that(
                payloads,
                has_items(
                    has_properties(type="approval_pending", call_id="call_echo"),
                    has_properties(type="approval_decision"),
                    is_function_call_output_end_turn(call_id="call_ui_end"),
                    has_finished_run(),
                ),
            )
    except CancelledError:
        pass
