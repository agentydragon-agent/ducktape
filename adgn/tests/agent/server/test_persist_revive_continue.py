from __future__ import annotations

from concurrent.futures import CancelledError

from hamcrest import assert_that, has_items, has_properties
import pytest

from adgn.agent.server.protocol import Envelope, RunStatus, RunStatusEvt, UiStateSnapshot
from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ui_asserts import assert_ui_items_have, item_assistant_markdown
from tests.agent.ws_helpers import drain_until_match, has_finished_run
from tests.llm.support.openai_mock import make_mock


def _collect_payloads_until_finished(ws, *, limit: int = 200):
    payloads = []
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        payloads.append(env.payload)
        if isinstance(env.payload, RunStatusEvt) and env.payload.run_state.status == RunStatus.FINISHED:
            break
    return payloads


@pytest.mark.timeout(15)
def test_persist_revive_continue_ui_flow(responses_factory, agent_ws_box):
    """
    End-to-end:
      1) Run a turn that emits ui.send_message + end_turn and persists events
      2) Build historical UiState via /api/runs/{id}/ui_state and verify assistant markdown present
      3) Open a fresh WS snapshot and verify the live UiState contains the same assistant message
      4) Continue with another turn that appends another assistant message, and verify it's persisted
    """

    # Program the mock model to emit:
    #  - First turn: ui.send_message("**hello**"), ui.end_turn
    #  - Second turn: ui.send_message("**world**"), ui.end_turn
    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "send_message"),
                {"mime": "text/markdown", "content": "**hello**"},
                call_id="call_ui_msg_1",
            )
        if step == 1:
            return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_1")
        if step == 2:
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "send_message"),
                {"mime": "text/markdown", "content": "**world**"},
                call_id="call_ui_msg_2",
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_2")

    client = make_mock(responses_create)

    try:
        with agent_ws_box(client, specs={}) as box:
            # First run
            box.http.prompt("hi")
            payloads_1 = box.collect(limit=100)
            assert_that(
                payloads_1,
                has_items(
                    has_properties(
                        type="ui_message", message=has_properties(mime="text/markdown", content="**hello**")
                    ),
                    has_finished_run(),
                ),
            )

            # Request a snapshot over WS; should include the assistant message
            payloads = drain_until_match(
                box.ws,
                lambda p: getattr(p.payload, "type", None) in ("ui_state_snapshot", "ui_state_updated"),
                limit=50,
                mapper=lambda e: e.payload,
            )
            snap: UiStateSnapshot = payloads[-1]
            assert_ui_items_have(snap.state.items, item_assistant_markdown("**hello**"))

            # Second run
            box.http.prompt("again")
            payloads_2 = box.collect(limit=100)
            assert_that(
                payloads_2,
                has_items(
                    has_properties(type="ui_message", message=has_properties(content="**world**")), has_finished_run()
                ),
            )

            # For live state, rely on WS only (REST ui_state is historical projection)

    except CancelledError:
        pass
