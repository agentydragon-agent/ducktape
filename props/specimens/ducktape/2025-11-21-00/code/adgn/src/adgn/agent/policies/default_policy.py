"""Packaged minimal policy program: allow UI messaging and resource reads."""

from __future__ import annotations

from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.agent.policies.scaffold import run
from adgn.mcp._shared.naming import build_mcp_function, server_matches

UI_SEND = build_mcp_function("ui", "send_message")
UI_END = build_mcp_function("ui", "end_turn")


def decide(req: PolicyRequest) -> PolicyResponse:
    if req.name in (UI_SEND, UI_END):
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="UI communication")
    if server_matches(req.name, server="resources"):
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="resource operations allowed")
    return PolicyResponse(decision=ApprovalDecision.ASK, rationale="default: ask")


if __name__ == "__main__":
    raise SystemExit(run(decide))
