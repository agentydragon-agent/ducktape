from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from adgn.agent.server.app import create_app
from adgn.agent.server.protocol import Envelope, UiStateSnapshot
from adgn.agent.server.state import AssistantMarkdownItem
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ws_helpers import (
    assert_finished,
    collect_payloads_until_finished,
    wait_for_accepted,
)
from tests.llm.support.openai_mock import make_mock


@pytest.mark.timeout(10)
def test_ws_restore_existing_agent_across_app_restart(monkeypatch, tmp_path, responses_factory):
    """
    Persist an agent (via HTTP), restart the app (new FastAPI instance pointing to the
    same SQLite DB), then connect WS to lazily start the live container and run a turn.

    This exercises: run -> save -> load -> resume with WS.
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
                    "mcp__ui__send_message",
                    {"mime": "text/markdown", "content": "**r1**"},
                    call_id="call_ui_msg_r1",
                )
            if i == 1:
                return responses_factory.make_tool_call(
                    "mcp__ui__end_turn", {}, call_id="call_ui_end_r1"
                )
            if i == 2:
                return responses_factory.make_tool_call(
                    "mcp__ui__send_message",
                    {"mime": "text/markdown", "content": "**r2**"},
                    call_id="call_ui_msg_r2",
                )
            return responses_factory.make_tool_call(
                "mcp__ui__end_turn", {}, call_id="call_ui_end_r2"
            )

        monkeypatch.setattr(
            "adgn.agent.runtime.container.build_client",
            lambda *a, **k: make_mock(responses_create),
        )

        # Open WS and run two turns to persist history
        with c1.websocket_connect(f"/ws?agent_id={agent_id}") as ws1:
            wait_for_accepted(ws1)
            ws1.send_json({"type": "send", "text": "hi"})
            collect_payloads_until_finished(ws1, limit=200)
            ws1.send_json({"type": "send", "text": "again"})
            collect_payloads_until_finished(ws1, limit=200)

    # Second app: same DB; WS connect should lazily start the container and snapshot should include all prior UI state
    app2 = create_app(require_static_assets=False)
    with TestClient(app2) as c2:
        # Optional: patch model, though we only snapshot (no turn yet)
        fake_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
        monkeypatch.setattr(
            "adgn.agent.runtime.container.build_client",
            lambda *a, **k: fake_client,
        )

        with c2.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
            # Should receive initial Accepted from server
            wait_for_accepted(ws)

            # Request a snapshot and verify both prior messages are present
            ws.send_json({"type": "get_snapshot"})
            saw_snapshot = False
            msgs: list[str] = []
            for _ in range(200):
                env = Envelope.model_validate(ws.receive_json())
                if isinstance(env.payload, UiStateSnapshot):
                    saw_snapshot = True
                    for it in env.payload.state.items:
                        if isinstance(it, AssistantMarkdownItem):
                            msgs.append(it.md)
                    break
            assert saw_snapshot, "ui_state_snapshot not received"
            assert "**r1**" in msgs and "**r2**" in msgs, f"missing restored messages: {msgs}"

            # Finally, run a prompt to confirm the live container is functional after lazy start
            ws.send_json({"type": "send", "text": "hi"})
            payloads = collect_payloads_until_finished(ws, limit=100)
            assert_finished(payloads)
