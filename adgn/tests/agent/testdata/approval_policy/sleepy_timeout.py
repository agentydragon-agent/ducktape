from time import sleep

from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.mcp._shared.constants import UI_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function

TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, "send_message"), arguments={}), ApprovalDecision.ASK)
]


def decide(req: PolicyRequest) -> PolicyResponse:
    sleep(1.0)
    return PolicyResponse(decision=ApprovalDecision.ASK, rationale="done")


if __name__ == "__main__":
    from adgn.agent.policies.scaffold import run_with_tests
    raise SystemExit(run_with_tests(decide, TEST_CASES))
