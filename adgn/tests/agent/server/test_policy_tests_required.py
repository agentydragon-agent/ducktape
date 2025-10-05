from __future__ import annotations

from fastapi.testclient import TestClient

from adgn.agent.server.app import create_app


def _wait_for(ws, pred, limit=20):
    for _ in range(limit):
        env = ws.receive_json()
        if pred(env):
            return env
    raise AssertionError("condition not met within message limit")


def _payload(env):
    return env.get("payload", {})


def test_set_policy_rejects_when_tests_missing():
    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        # Create a default agent
        r = c.post("/api/agents", json={"preset": "default"})
        assert r.status_code == 200, r.text
        agent_id = r.json()["id"]

        # Connect WS and wait accepted
        with c.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
            _wait_for(ws, lambda e: _payload(e).get("type") == "accepted")

            policy = "def decide(ctx):\n  return (PolicyDecision.ALLOW, 'ok')\n"
            ws.send_json({"type": "set_policy", "content": policy})

            # Expect an error INVALID_COMMAND because TEST_CASES are missing
            env = _wait_for(ws, lambda e: _payload(e).get("type") == "error")
            p = _payload(env)
            assert p.get("code") == "INVALID_COMMAND"


def test_set_policy_rejects_when_test_fails():
    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        r = c.post("/api/agents", json={"preset": "default"})
        assert r.status_code == 200, r.text
        agent_id = r.json()["id"]

        with c.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
            _wait_for(ws, lambda e: _payload(e).get("type") == "accepted")

            # Define a policy with a failing test case (expects ASK for UI send_message)
            policy = (
                "def decide(ctx):\n"
                "  return (PolicyDecision.ALLOW, 'ok')\n"
                "TEST_CASES = [\n"
                "  (ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ASK),\n"
                "]\n"
            )
            ws.send_json({"type": "set_policy", "content": policy})

            env = _wait_for(ws, lambda e: _payload(e).get("type") == "error")
            p = _payload(env)
            assert p.get("code") == "INVALID_COMMAND"
