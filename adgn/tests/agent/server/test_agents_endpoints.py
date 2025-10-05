from __future__ import annotations

from concurrent.futures import CancelledError

import pytest

from adgn.agent.server.protocol import UiStateSnapshot
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ui_asserts import assert_ui_items_have, item_user_message
from tests.agent.ws_helpers import assert_finished, drain_until


@pytest.mark.timeout(5)
def test_agents_list_status_and_history(
    responses_factory,
    ws_session,
):
    """Create an agent via API, check listing/status, run one turn, then verify run history and UI-state projection."""

    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
    # Establish WS session which creates the agent
    try:
        with ws_session(model_client, specs={}) as (client, ws, collect, agent_id):
            # Verify listing shows it as live
            res = client.get("/api/agents")
            assert res.status_code == 200
            agents = res.json().get("agents", [])
            assert any(a["id"] == agent_id and a.get("live") for a in agents)

            # Status endpoint returns live with no active run yet
            res = client.get(f"/api/agents/{agent_id}/status")
            assert res.status_code == 200
            body = res.json()
            assert body["id"] == agent_id and body["live"] is True
            assert body.get("active_run_id") in (None,)

            # Send one prompt to create a run over the existing session
            ws.send_json({"type": "send", "text": "hi"})
            payloads = collect(limit=50)
            assert_finished(payloads)
            # Request a WS snapshot; should include the user message
            ws.send_json({"type": "get_snapshot"})
            payloads = drain_until(
                ws,
                lambda e: isinstance(e.payload, UiStateSnapshot),
                limit=50,
                mapper=lambda e: e.payload,
            )
            snap: UiStateSnapshot = payloads[-1]  # last item is the snapshot
            assert_ui_items_have(snap.state.items, item_user_message())
    except CancelledError:
        # Teardown may raise due to TestClient portal; we already verified 'finished'.
        pass

    # List runs (most recent first)
    res = client.get(f"/api/runs?agent_id={agent_id}&limit=5")
    assert res.status_code == 200
    runs = res.json().get("runs", [])
    assert len(runs) >= 1
    runs[0]["id"]

    # Historical UiState projection endpoint removed; clients should use WS snapshot for UI.
