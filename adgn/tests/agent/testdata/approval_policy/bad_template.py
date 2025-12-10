from adgn.agent.approvals import WellKnownTools
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.agent.policies.scaffold import run_with_tests
from adgn.mcp._shared.constants import SEATBELT_EXEC_MOUNT_PREFIX, UI_MOUNT_PREFIX
from adgn.mcp._shared.naming import build_mcp_function, tool_matches

TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_MOUNT_PREFIX, WellKnownTools.SEND_MESSAGE), arguments="{}"), ApprovalDecision.ASK)
]


def decide(req: PolicyRequest) -> PolicyResponse:
    if tool_matches(req.name, server=SEATBELT_EXEC_MOUNT_PREFIX, tool=WellKnownTools.SANDBOX_EXEC):
        # Intentionally error to simulate failing seatbelt resolution → deny-abort upstream
        raise RuntimeError("seatbelt policy resolution failed")
    return PolicyResponse(decision=ApprovalDecision.ASK, rationale="default")


if __name__ == "__main__":
    raise SystemExit(run_with_tests(decide, TEST_CASES))
