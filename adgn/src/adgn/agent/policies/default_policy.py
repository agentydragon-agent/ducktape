"""Packaged minimal policy program: allow UI messaging and resource reads."""

from __future__ import annotations

from adgn.agent.policies.helpers import split_tool_name
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.agent.policies.scaffold import run


def decide(req: PolicyRequest) -> PolicyResponse:
    server, tool = split_tool_name(req.name)
    if server == "ui" and tool in ("send_message", "end_turn"):
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="UI communication")
    if server == "resources":
        return PolicyResponse(
            decision=ApprovalDecision.ALLOW, rationale="resource operations allowed"
        )
    return PolicyResponse(decision=ApprovalDecision.ASK, rationale="default: ask")


if __name__ == "__main__":
    raise SystemExit(run(decide))
