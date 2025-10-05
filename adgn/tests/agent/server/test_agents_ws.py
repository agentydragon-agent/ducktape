from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from adgn.agent.server.agents_ws import (
    AgentCreatedMsg,
    AgentsHubMsg,
    AgentsSnapshotMsg,
    AgentStatusMsg,
)
from adgn.agent.server.app import create_app
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ws_helpers import wait_for_accepted


def _recv_until(ws, predicate, limit=10):
    msgs = []
    for _ in range(limit):
        msg = ws.receive_json()
        msgs.append(msg)
        if predicate(msg):
            return msg, msgs
    raise AssertionError("expected message not received; got: %r" % msgs)


def test_agents_ws_initial_and_create_broadcast():
    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        with c.websocket_connect("/ws/agents") as ws:
            init = ws.receive_json()
            msg = TypeAdapter(AgentsHubMsg).validate_python(init)
            assert isinstance(msg, AgentsSnapshotMsg), msg
            assert isinstance(msg.data.agents, list)

            r = c.post("/api/agents", json={"preset": "default"})
            assert r.status_code == 200
            agent_id = r.json()["id"]

            def _have_create_and_status(acc):
                kinds = []
                ids_ok = True
                for raw in acc:
                    m = TypeAdapter(AgentsHubMsg).validate_python(raw)
                    kinds.append(type(m).__name__)
                    if isinstance(m, (AgentCreatedMsg, AgentStatusMsg)):
                        if (getattr(m, "data").id) != agent_id:
                            ids_ok = False
                return ("AgentCreatedMsg" in kinds and "AgentStatusMsg" in kinds) and ids_ok

            # Collect a few messages and ensure we saw both notifications for our id
            acc: list[dict] = []
            for _ in range(5):
                acc.append(ws.receive_json())
                if _have_create_and_status(acc):
                    break
            assert _have_create_and_status(acc), acc


def test_agents_ws_status_on_agent_ws_connect():
    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        # Create an agent first
        r = c.post("/api/agents", json={"preset": "default"})
        assert r.status_code == 200
        agent_id = r.json()["id"]

        with c.websocket_connect("/ws/agents") as hub:
            init = hub.receive_json()
            _ = TypeAdapter(AgentsHubMsg).validate_python(init)

            # Opening per-agent WS should cause a live:true status broadcast on the hub
            with c.websocket_connect(f"/ws?agent_id={agent_id}") as agent_ws:
                # Wait for enveloped Accepted on agent ws so it's fully open
                _ = wait_for_accepted(agent_ws)

                def _is_live_status(m):
                    parsed = TypeAdapter(AgentsHubMsg).validate_python(m)
                    return (
                        isinstance(parsed, AgentStatusMsg)
                        and parsed.data.id == agent_id
                        and parsed.data.live is True
                    )

                _, acc = _recv_until(hub, _is_live_status, limit=5)
                assert any(_is_live_status(m) for m in acc), acc


def test_agents_ws_run_status_mirrors(agent_app_client, ws_session, responses_factory):
    app, client = agent_app_client
    # Open hub first to receive broadcasts
    with client.websocket_connect("/ws/agents") as hub:
        init = hub.receive_json()
        assert init.get("type") == "agents_snapshot"

        # Fake model that returns a simple assistant message
        model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])

        with ws_session(model_client, specs={}) as (_client, ws, collect, agent_id):
            # Agent WS accepted
            # Send a run
            ws.send_json({"type": "send", "text": "hello"})

            # Expect a live:true with active_run_id set
            def _have_active(m):
                parsed = TypeAdapter(AgentsHubMsg).validate_python(m)
                return (
                    isinstance(parsed, AgentStatusMsg)
                    and parsed.data.id == agent_id
                    and parsed.data.live is True
                    and bool(parsed.data.active_run_id)
                )

            _, acc1 = _recv_until(hub, _have_active, limit=10)
            assert any(_have_active(m) for m in acc1), acc1

            # Expect a follow-up live:true with active_run_id cleared when finished
            def _have_finished(m):
                parsed = TypeAdapter(AgentsHubMsg).validate_python(m)
                return (
                    isinstance(parsed, AgentStatusMsg)
                    and parsed.data.id == agent_id
                    and parsed.data.live is True
                    and (parsed.data.active_run_id is None or parsed.data.active_run_id == "")
                )

            _, acc2 = _recv_until(hub, _have_finished, limit=20)
            assert any(_have_finished(m) for m in acc2), acc2
