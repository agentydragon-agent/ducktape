from __future__ import annotations

from tests.agent.testdata.approval_policy import fetch_policy
from tests.llm.support.openai_mock import make_mock


def test_set_policy_rejects_when_tests_missing(agent_app_client, create_live_agent, agent_ws_box):
    app, c = agent_app_client
    # Create a default agent
    _ = create_live_agent(c, specs={})

    # Connect WS and wait accepted
    # Use agent_ws_box for a unified interface
    dummy_client = make_mock(lambda req: None)
    with agent_ws_box(dummy_client, specs={}) as box:
        policy = fetch_policy("missing_tests")
        r = box.http.set_policy(policy)
        # New behavior: self-check runs policy once; invalid programs return 400
        assert r.status_code == 400


def test_set_policy_rejects_when_test_fails(agent_app_client, create_live_agent, agent_ws_box):
    app, c = agent_app_client
    _ = create_live_agent(c, specs={})

    dummy_client = make_mock(lambda req: None)
    with agent_ws_box(dummy_client, specs={}) as box:
        # Policy with a failing test case (expects ASK for UI send_message)
        policy = fetch_policy("failing_tests")
        r = box.http.set_policy(policy)
        assert r.status_code == 400
