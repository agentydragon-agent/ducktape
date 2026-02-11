from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.mcp._shared.naming import build_mcp_function

TEST_CASES = [
    # Expect DENY_ABORT for UI send_message, but decide() returns ALLOW → preflight fails
    (PolicyRequest(name=build_mcp_function("ui", "send_message"), arguments={}), ApprovalDecision.DENY_ABORT)
]


def decide(req: PolicyRequest) -> PolicyResponse:
    # Intentionally violate expected semantics (used in tests)
    return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="ok")


if __name__ == "__main__":
    from adgn.agent.policies.scaffold import run_with_tests
    raise SystemExit(run_with_tests(decide, TEST_CASES))
