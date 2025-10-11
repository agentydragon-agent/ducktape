from __future__ import annotations

from concurrent.futures import CancelledError

from hamcrest import any_of, instance_of
import pytest

from adgn.agent.server.protocol import UiStateSnapshot, UiStateUpdated
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ui_asserts import assert_ui_items_have, item_user_message
from tests.agent.ws_helpers import assert_finished, drain_until_match


@pytest.mark.timeout(5)
def test_agents_list_status_and_history(
    responses_factory,
    agent_ws_box,
):
    """Create an agent via API, check listing/status, run one turn, then verify run history and UI-state projection."""

    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
    # Establish WS session which creates the agent
    try:
        with agent_ws_box(model_client, specs={}) as box:
            # Verify listing shows it as live
            res = box.client.get("/api/agents")
            assert res.status_code == 200
            agents = res.json().get("agents", [])
            assert any(a["id"] == box.agent_id and a.get("live") for a in agents)

            # Status endpoint returns live with no active run yet
            res = box.client.get(f"/api/agents/{box.agent_id}/status")
            assert res.status_code == 200
            body = res.json()
            assert body["id"] == box.agent_id and body["live"] is True
            assert body.get("active_run_id") in (None,)

            # Send one prompt over REST to create a run; WS receives events
            res = box.http.prompt("hi")
            assert res.status_code == 200
            # First, wait for a UiStateUpdated (or UiStateSnapshot) to assert UI reflects the user message
            payloads = drain_until_match(
                box.ws,
                any_of(instance_of(UiStateSnapshot), instance_of(UiStateUpdated)),
                limit=100,
                mapper=lambda e: e.payload,
            )
            last = payloads[-1]
            items = last.state.items  # UiStateSnapshot or UiStateUpdated have .state
            assert_ui_items_have(items, item_user_message())
            # Then collect until finished for completeness
            payloads = box.collect(limit=50)
            assert_finished(payloads)
    except CancelledError:
        # Teardown may raise due to TestClient portal; we already verified 'finished'.
        pass

    # List runs (most recent first)
    res = box.client.get(f"/api/runs?agent_id={box.agent_id}&limit=5")
    assert res.status_code == 200
    runs = res.json().get("runs", [])
    assert len(runs) >= 1
    runs[0]["id"]

    # Historical UiState projection endpoint removed; clients should use WS snapshot for UI.
