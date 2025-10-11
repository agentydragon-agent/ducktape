from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse, ApprovalDecision
from adgn.agent.policies.helpers import split_tool_name
from adgn.agent.approvals import WellKnownTools
from adgn.mcp._shared.constants import UI_SERVER_NAME, SEATBELT_EXEC_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function


TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE), arguments={}), ApprovalDecision.ASK)
]


def decide(req: PolicyRequest) -> PolicyResponse:
    server, tool = split_tool_name(req.name)
    if server == SEATBELT_EXEC_SERVER_NAME and tool == WellKnownTools.SANDBOX_EXEC:
        # Intentionally error to simulate failing seatbelt resolution → deny-abort upstream
        raise RuntimeError("seatbelt policy resolution failed")
    return PolicyResponse(decision=ApprovalDecision.ASK, rationale="default")


if __name__ == "__main__":
    from adgn.agent.policies.scaffold import run_with_tests
    raise SystemExit(run_with_tests(decide, TEST_CASES))
