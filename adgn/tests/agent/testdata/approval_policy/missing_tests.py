from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse, ApprovalDecision


def decide(req: PolicyRequest) -> PolicyResponse:
    return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="ok")


if __name__ == "__main__":
    from adgn.agent.policies.scaffold import run
    raise SystemExit(run(decide))
