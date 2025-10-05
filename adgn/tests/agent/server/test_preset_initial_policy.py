from __future__ import annotations

from textwrap import indent

from fastapi.testclient import TestClient

from adgn.agent.server.app import create_app


def test_preset_initial_policy_loaded_into_engine(tmp_path, monkeypatch):
    # Prepare a preset with an explicit approval policy
    d = tmp_path / "presets"
    d.mkdir()
    policy = (
        "from adgn.agent.approvals import PolicyDecision, WellKnownServers, WellKnownTools, ApprovalContext\n"
        "def decide(ctx):\n"
        "  return (PolicyDecision.ALLOW, 'ok')\n"
        "TEST_CASES = [\n"
        "  (ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ALLOW),\n"
        "]\n"
    )
    yaml_text = (
        "name: policytest\n"
        "description: preset with initial policy\n"
        "system: Initial system\n"
        "approval_policy: |\n" + indent(policy, "  ") + "\n"
        "specs: {}\n"
    )
    (d / "policytest.yaml").write_text(yaml_text, encoding="utf-8")
    monkeypatch.setenv("ADGN_AGENT_PRESETS_DIR", str(d))

    app = create_app(require_static_assets=False)
    with TestClient(app) as c:
        # Create agent from preset
        r = c.post("/api/agents", json={"preset": "policytest"})
        assert r.status_code == 200, r.text
        agent_id = r.json()["id"]
        # Open WS and request snapshot; verify approval_policy content matches
        with c.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
            # accepted
            env = ws.receive_json()
            assert env.get("payload", {}).get("type") == "accepted"
            # request snapshot
            ws.send_json({"type": "get_snapshot"})
            # Expect several payloads; find the snapshot
            for _ in range(10):
                env = ws.receive_json()
                payload = env.get("payload", {})
                if payload.get("type") == "snapshot":
                    ap = payload.get("approval_policy") or {}
                    content = ap.get("content") or ""
                    assert "TEST_CASES" in content and "PolicyDecision.ALLOW" in content
                    break
            else:
                raise AssertionError("snapshot not received")
