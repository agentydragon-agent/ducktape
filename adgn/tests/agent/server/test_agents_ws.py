from __future__ import annotations

from hamcrest import assert_that, has_item
from pydantic import TypeAdapter
import pytest

from adgn.agent.server.agents_ws import AgentCreatedMsg, AgentsHubMsg, AgentsSnapshotMsg, AgentStatusMsg
from tests.agent.ws_helpers import (
    ACTIVE_RUN_CLEARED,
    ACTIVE_RUN_SET,
    agent_status,
    drain_json_until_match,
    wait_for_accepted,
)
from tests.llm.support.openai_mock import FakeOpenAIModel


def test_agents_ws_initial_and_create_broadcast(ws_hub):
    client, ws = ws_hub
    init = ws.receive_json()
    msg: AgentsHubMsg = TypeAdapter(AgentsHubMsg).validate_python(init)
    assert isinstance(msg, AgentsSnapshotMsg), msg
    assert isinstance(msg.data.agents, list)

    r = client.post("/api/agents", json={"preset": "default"})
    assert r.status_code == 200
    agent_id = r.json()["id"]

    def _have_create_and_status(acc):
        kinds = []
        ids_ok = True
        for raw in acc:
            m: AgentsHubMsg = TypeAdapter(AgentsHubMsg).validate_python(raw)
            kinds.append(type(m).__name__)
            if isinstance(m, AgentCreatedMsg | AgentStatusMsg) and (m.data.id) != agent_id:
                ids_ok = False
        return ("AgentCreatedMsg" in kinds and "AgentStatusMsg" in kinds) and ids_ok

    acc: list[dict] = []
    for _ in range(5):
        acc.append(ws.receive_json())
        if _have_create_and_status(acc):
            break
    assert _have_create_and_status(acc), acc


def test_agents_ws_status_on_agent_ws_connect(ws_hub, agent_app_client, patch_agent_build_client, responses_factory):
    client, hub = ws_hub
    patch_agent_build_client(FakeOpenAIModel([responses_factory.make_assistant_message("ok")]))
    # Create an agent first
    r = client.post("/api/agents", json={"preset": "default"})
    assert r.status_code == 200
    agent_id = r.json()["id"]

    init = hub.receive_json()
    _ = TypeAdapter(AgentsHubMsg).validate_python(init)

    # Opening per-agent WS should cause a live:true status broadcast on the hub
    with client.websocket_connect(f"/ws?agent_id={agent_id}") as agent_ws:
        _ = wait_for_accepted(agent_ws)

        # Hub emits bare typed messages (not Envelope); use matcher-based drain
        acc = drain_json_until_match(
            hub, agent_status(agent_id, active_run_id=None, live=True), limit=10, mapper=lambda m: m
        )
        assert_that(acc, has_item(agent_status(agent_id, active_run_id=None, live=True)))


@pytest.mark.timeout(15)
def test_agents_ws_run_status_mirrors(agent_app_client, agent_ws_box, responses_factory):
    app, client = agent_app_client
    # Open hub first to receive broadcasts
    with client.websocket_connect("/ws/agents") as hub:
        init = hub.receive_json()
        assert init.get("type") == "agents_snapshot"

        # Fake model that returns a simple assistant message
        model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])

        with agent_ws_box(model_client, specs={}) as box:
            # Agent WS accepted
            # Send a run
            r = box.http.prompt("hello")
            assert r.status_code == 200

            # Expect a live:true with active_run_id set; drain until a status for this agent
            acc1 = drain_json_until_match(
                hub, agent_status(box.agent_id, active_run_id=ACTIVE_RUN_SET), limit=40, mapper=lambda m: m
            )
            assert_that(acc1, has_item(agent_status(box.agent_id, active_run_id=ACTIVE_RUN_SET)))

            # Expect a follow-up live:true with active_run_id cleared when finished
            # Ensure the run finished on the agent WS to avoid missing the hub update
            _ = box.collect(limit=180)
            acc2 = drain_json_until_match(
                hub, agent_status(box.agent_id, active_run_id=ACTIVE_RUN_CLEARED), limit=60, mapper=lambda m: m
            )
            assert_that(acc2, has_item(agent_status(box.agent_id, active_run_id=ACTIVE_RUN_CLEARED)))
