from adgn.agent.approvals import WellKnownTools
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.mcp._shared.constants import UI_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function

TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE), arguments={}), ApprovalDecision.ALLOW)
]


def decide(req: PolicyRequest) -> PolicyResponse:
    # Ensure arguments round-trip
    _ = req.arguments
    return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="ok")


if __name__ == "__main__":
    from adgn.agent.policies.scaffold import run_with_tests
    raise SystemExit(run_with_tests(decide, TEST_CASES))
