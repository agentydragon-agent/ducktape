"""Approval policy test fixtures package.

Provides fetch_policy(name) to load policy source text from this package.
"""

from __future__ import annotations

from importlib.resources import files


def fetch_policy(name: str) -> str:
    """Return policy Python source from a file named "<name>.py" in this package."""
    return files(__name__).joinpath(f"{name}.py").read_text(encoding="utf-8").strip()


def make_policy(
    *,
    decision_expr: str,
    server: str,
    tool: str,
    default: str = "ask",
    doc: str | None = None,
) -> str:
    """
    Build a minimal ApprovalPolicy source that returns `decision_expr` for a given
    server/tool, and `default` ('ask' or 'allow') otherwise. UI send_message is
    always allowed via TEST_CASES to satisfy baseline constraints.

    decision_expr examples: 'PolicyDecision.DENY_CONTINUE', 'PolicyDecision.ASK'
    """
    if default not in {"ask", "allow"}:
        raise ValueError("default must be 'ask' or 'allow'")
    default_expr = "PolicyDecision.ASK" if default == "ask" else "PolicyDecision.ALLOW"
    doc = doc or f"policy for {server}.{tool} returns explicit decision; default {default}"
    tool_name = f"mcp__{server}__{tool}"
    header = (
        "from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse, ApprovalDecision\n"
        "from adgn.agent.policies.helpers import split_tool_name\n"
        "from adgn.agent.approvals import WellKnownTools\n"
        "from adgn.agent.policies.scaffold import run_with_tests\n"
        "from adgn.mcp._shared.constants import UI_SERVER_NAME\n"
        "from adgn.mcp._shared.naming import build_mcp_function\n\n"
    )
    body = f"""
# {doc}
TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE), arguments={{}}), ApprovalDecision.ALLOW),
]

def decide(req: PolicyRequest) -> PolicyResponse:
    server, tool = split_tool_name(req.name)
    # Always allow UI send_message to satisfy baseline TEST_CASES
    if server == UI_SERVER_NAME and tool == WellKnownTools.SEND_MESSAGE:
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale='ui allow')
    if req.name == '{tool_name}':
        return PolicyResponse(decision={decision_expr}, rationale='explicit')
    return PolicyResponse(decision={default_expr}, rationale='default')

if __name__ == '__main__':
    raise SystemExit(run_with_tests(decide, TEST_CASES))
"""
    return header + body
