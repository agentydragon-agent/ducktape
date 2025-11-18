from __future__ import annotations

import pytest
from pydantic import TypeAdapter
import yaml

from adgn.agent.presets import AgentPreset
from adgn.agent.server.protocol import Envelope, Snapshot
from tests.agent.ws_helpers import wait_for_accepted
from tests.llm.support.openai_mock import FakeOpenAIModel


def test_preset_initial_policy_loaded_into_engine(
    agent_app_client, tmp_path, monkeypatch, policy_ui_send_message_allow, patch_agent_build_client, responses_factory
):
    # Prepare a preset with an explicit approval policy
    d = tmp_path / "presets"
    d.mkdir()
    preset = AgentPreset(
        name="policytest",
        description="preset with initial policy",
        system="Initial system",
        approval_policy=policy_ui_send_message_allow,
        specs={},
    )
    (d / "policytest.yaml").write_text(
        yaml.safe_dump(preset.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setenv("ADGN_AGENT_PRESETS_DIR", str(d))

    _app, c = agent_app_client
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
    patch_agent_build_client(model_client)
    # Create agent from preset
    r = c.post("/api/agents", json={"preset": "policytest"})
    assert r.status_code == 200, r.text
    agent_id = r.json()["id"]

    # Connect to policy channel to verify initial policy is loaded
    with c.websocket_connect(f"/ws/policy?agent_id={agent_id}") as ws_policy:
        # Policy channel sends Accepted on connect
        env = Envelope.model_validate(ws_policy.receive_json())
        assert env.payload.type == "accepted"

        # The server pushes a PolicySnapshot on connect
        for _ in range(20):
            env = Envelope.model_validate(ws_policy.receive_json())
            if env.payload.type == "policy_snapshot":
                policy = env.payload.policy
                content = policy.content
                assert "class ApprovalPolicy" in content
                assert "TEST_CASES" in content
                break
        else:
            raise AssertionError("policy_snapshot not received")


def test_preset_policy_with_failing_tests_falls_back(
    agent_app_client, tmp_path, monkeypatch, policy_failing_tests, patch_agent_build_client, responses_factory
):
    # Prepare a preset with an explicit approval policy that fails its test
    d = tmp_path / "presets"
    d.mkdir()
    marker = "# failing_test_marker"
    policy = policy_failing_tests + f"\n{marker}\n"
    preset = AgentPreset(
        name="policyfail",
        description="preset with failing policy",
        system="Initial system",
        approval_policy=policy,
        specs={},
    )
    (d / "policyfail.yaml").write_text(
        yaml.safe_dump(preset.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setenv("ADGN_AGENT_PRESETS_DIR", str(d))

    _app, c = agent_app_client
    model_client = FakeOpenAIModel([responses_factory.make_assistant_message("ok")])
    patch_agent_build_client(model_client)
    # Create agent from preset
    r = c.post("/api/agents", json={"preset": "policyfail"})
    assert r.status_code == 200, r.text
    agent_id = r.json()["id"]

    # Connect to policy channel to verify fallback policy is loaded (not the failing one)
    with c.websocket_connect(f"/ws/policy?agent_id={agent_id}") as ws_policy:
        # Policy channel sends Accepted on connect
        env = Envelope.model_validate(ws_policy.receive_json())
        assert env.payload.type == "accepted"

        # The server pushes a PolicySnapshot on connect
        for _ in range(20):
            env = Envelope.model_validate(ws_policy.receive_json())
            if env.payload.type == "policy_snapshot":
                policy = env.payload.policy
                content = policy.content
                # Verify we do NOT see the marker from failing policy
                assert marker not in content
                assert "class ApprovalPolicy" in content
                break
        else:
            raise AssertionError("policy_snapshot not received")
