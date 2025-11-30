"""Approval policy test fixtures package.

Provides fetch_policy(name) to load policy source text from this package.
"""

from __future__ import annotations

from importlib.resources import files
from typing import cast

from adgn.mcp._shared.naming import build_mcp_function


def fetch_policy(name: str) -> str:
    """Return policy Python source from a file named "<name>.py" in this package."""
    return cast(str, files(__name__).joinpath(f"{name}.py").read_text(encoding="utf-8"))


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
    build_mcp_function(server, tool)
    header = (
        "from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse, ApprovalDecision\n"
        "from adgn.agent.approvals import WellKnownTools\n"
        "from adgn.agent.policies.scaffold import run_with_tests\n"
        "from adgn.mcp._shared.constants import UI_SERVER_NAME\n"
        "from adgn.mcp._shared.naming import build_mcp_function, tool_matches\n\n"
    )
    body = f"""
# {doc}
TEST_CASES = [
    (PolicyRequest(name=build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE), arguments={{}}), ApprovalDecision.ALLOW),
]

def decide(req: PolicyRequest) -> PolicyResponse:
    # Always allow UI send_message to satisfy baseline TEST_CASES
    if tool_matches(req.name, server=UI_SERVER_NAME, tool=WellKnownTools.SEND_MESSAGE):
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale='ui allow')
    if tool_matches(req.name, server='{server}', tool='{tool}'):
        return PolicyResponse(decision={decision_expr}, rationale='explicit')
    return PolicyResponse(decision={default_expr}, rationale='default')

if __name__ == '__main__':
    raise SystemExit(run_with_tests(decide, TEST_CASES))
"""
    return header + body
