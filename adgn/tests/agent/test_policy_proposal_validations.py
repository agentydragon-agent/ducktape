from __future__ import annotations

from concurrent.futures import CancelledError

from hamcrest import assert_that, has_properties

from adgn.agent.server import protocol
from tests.llm.support.openai_mock import make_mock

Envelope = protocol.Envelope


def _collect_until(ws, pred, limit=200):
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        if pred(env):
            return env
    raise AssertionError("condition not met")


def test_proposal_approve_rejects_on_failing_tests(responses_factory, ws_session):
    # Model proposes a policy with a failing TEST_CASES; approval should be rejected
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            src = (
                "def decide(ctx):\n"
                "  return (PolicyDecision.ALLOW, 'ok')\n"
                "TEST_CASES = [\n"
                "  (ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ASK),\n"
                "]\n"
            )
            return responses_factory.make_tool_call(
                "mcp__approval_policy__propose",
                {"policy_python_code": src, "rationale": "test"},
                call_id="call_propose",
            )
        return responses_factory.make_tool_call("mcp__ui__end_turn", {}, call_id="call_ui_end")

    client = make_mock(responses_create)

    try:
        with ws_session(client, specs={}) as (client_ws, ws, collect, agent_id):
            # Send a message that causes the model to propose a policy
            ws.send_json({"type": "send", "text": "propose failing policy"})
            # Drain until we see function_call_output for propose
            saw_proposal = False
            proposal_id = None
            for env in collect(limit=100):
                if env.type == "function_call_output" and env.call_id == "call_propose":
                    pid = (env.result or {}).get("structuredContent", {}).get("proposal_id")
                    if pid:
                        proposal_id = pid
                        saw_proposal = True
                        break
            assert saw_proposal and proposal_id

            # Attempt to approve; expect an error due to failing tests
            ws.send_json(
                {"type": "apply_proposal", "proposal_id": proposal_id, "decision": "approve"}
            )
            env = _collect_until(ws, lambda e: e.payload.type == "error")
            assert_that(env.payload, has_properties(type="error", code="INVALID_COMMAND"))

    except CancelledError:
        pass
