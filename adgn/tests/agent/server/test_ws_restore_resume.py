from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from adgn.agent.server.app import create_app
from adgn.agent.server.protocol import Envelope, UiStateSnapshot
from adgn.agent.server.state import AssistantMarkdownItem
from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ws_helpers import assert_finished, collect_payloads_until_finished, wait_for_accepted
from tests.llm.support.openai_mock import FakeOpenAIModel, make_mock


@pytest.mark.timeout(10)
def test_ws_restore_existing_agent_across_app_restart(
    monkeypatch, tmp_path, responses_factory, make_agent_http, patch_agent_build_client
):
    """
    Persist an agent (via HTTP), restart the app (new FastAPI instance pointing to the
    same SQLite DB), then connect to modular channels to lazily start the live container
    and run a turn.

    This exercises: run -> save -> load -> resume with modular channels.
    """

    db_path = tmp_path / "agent.sqlite"
    monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(db_path))

    # First app: create a persisted agent via HTTP API and run two UI-producing turns
    app1 = create_app(require_static_assets=False)
    with TestClient(app1) as c1:
        # Create agent from built-in default preset
        resp = c1.post("/api/agents", json={"preset": "default"})
        assert resp.status_code == 200
        agent_id = resp.json()["id"]

        # Program the model to emit two turns: send_message("**r1**"), end_turn; then send_message("**r2**"), end_turn
        state = {"i": 0}

        async def responses_create(_req):
            i = state["i"]
            state["i"] = i + 1
            if i == 0:
                return responses_factory.make_tool_call(
                    build_mcp_function("ui", "send_message"),
                    {"mime": "text/markdown", "content": "**r1**"},
                    call_id="call_ui_msg_r1",
                )
            if i == 1:
                return responses_factory.make_tool_call(
                    build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_r1"
                )
            if i == 2:
                return responses_factory.make_tool_call(
                    build_mcp_function("ui", "send_message"),
                    {"mime": "text/markdown", "content": "**r2**"},
                    call_id="call_ui_msg_r2",
                )
            return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_r2")

        patch_agent_build_client(make_mock(responses_create))

        # Open session and UI channels, run two turns to persist history
        with c1.websocket_connect(f"/ws/session?agent_id={agent_id}") as ws_session:
            with c1.websocket_connect(f"/ws/ui?agent_id={agent_id}") as ws_ui:
                # Session channel sends Accepted on connect
                sess_env = Envelope.model_validate(ws_session.receive_json())
                assert sess_env.payload.type == "accepted"

                # UI channel sends Accepted on connect
                ui_env = Envelope.model_validate(ws_ui.receive_json())
                assert ui_env.payload.type == "accepted"

                # Start turns via REST; session channel carries run events
                http1 = make_agent_http(c1, agent_id)
                r1 = http1.prompt("hi")
                assert r1.status_code == 200
                assert (r1.json() or {}).get("ok") is True
                collect_payloads_until_finished(ws_session, limit=200)

                r2 = http1.prompt("again")
                assert r2.status_code == 200
                assert (r2.json() or {}).get("ok") is True
                collect_payloads_until_finished(ws_session, limit=200)

    # Second app: same DB; connect to UI channel to verify restored state
    app2 = create_app(require_static_assets=False)
    with TestClient(app2) as c2:
        # Optional: patch model, though we only snapshot (no turn yet)
        fake_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
        patch_agent_build_client(fake_client)

        with c2.websocket_connect(f"/ws/ui?agent_id={agent_id}") as ws_ui:
            # Should receive initial Accepted from server
            ui_env = Envelope.model_validate(ws_ui.receive_json())
            assert ui_env.payload.type == "accepted"

            # On connect, server pushes UiStateSnapshot; verify prior messages are present
            saw_snapshot = False
            msgs: list[str] = []
            for _ in range(200):
                env = Envelope.model_validate(ws_ui.receive_json())
                if isinstance(env.payload, UiStateSnapshot):
                    saw_snapshot = True
                    for it in env.payload.state.items:
                        if isinstance(it, AssistantMarkdownItem):
                            msgs.append(it.md)
                    break
            assert saw_snapshot, "ui_state_snapshot not received"
            assert "**r1**" in msgs, f"missing restored message r1: {msgs}"
            assert "**r2**" in msgs, f"missing restored message r2: {msgs}"

            # Finally, run a prompt via REST to confirm live container works
            # Connect session channel for run events
            with c2.websocket_connect(f"/ws/session?agent_id={agent_id}") as ws_session:
                sess_env = Envelope.model_validate(ws_session.receive_json())
                assert sess_env.payload.type == "accepted"

                http2 = make_agent_http(c2, agent_id)
                r3 = http2.prompt("hi")
                assert r3.status_code == 200
                assert (r3.json() or {}).get("ok") is True
                payloads = collect_payloads_until_finished(ws_session, limit=100)
                assert_finished(payloads)
