from __future__ import annotations

from adgn.agent.server.protocol import Envelope
from adgn.mcp._shared.naming import build_mcp_function
from tests.llm.support.openai_mock import make_mock


def _collect_until(ws, pred, limit=200):
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        if pred(env):
            return env
    raise AssertionError("condition not met")


def test_proposal_approve_rejects_on_failing_tests(responses_factory, agent_ws_box, policy_failing_tests: str):
    # Model proposes a policy with a failing TEST_CASES; approval should be rejected
    async def responses_create(_req):
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    client = make_mock(responses_create)

    with agent_ws_box(client, specs={}) as box:
        # Set policy via HTTP; expect ok=false due to failing tests
        r = box.http.set_policy(policy_failing_tests)
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is False
