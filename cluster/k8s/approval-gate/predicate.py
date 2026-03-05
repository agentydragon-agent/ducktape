from approval_gate.predicates import NeedsHumanDecision


def decide(server_namespace: str, tool_name: str, arguments: dict) -> NeedsHumanDecision:
    return NeedsHumanDecision()
