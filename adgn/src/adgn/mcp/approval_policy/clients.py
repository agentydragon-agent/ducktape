from __future__ import annotations

from typing import Final

from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.mcp._shared.constants import APPROVAL_POLICY_SERVER_NAME_APPROVER, APPROVAL_POLICY_SERVER_NAME_READER
from adgn.mcp.approval_policy.server import ApproveProposalArgs, RejectProposalArgs, SetPolicyTextArgs
from adgn.mcp.stubs.server_stubs import ServerStub

READER_SERVER_NAME: Final[str] = APPROVAL_POLICY_SERVER_NAME_READER
APPROVER_SERVER_NAME: Final[str] = APPROVAL_POLICY_SERVER_NAME_APPROVER


class PolicyReaderStub(ServerStub):
    """Typed stub for the approval policy reader MCP server."""

    async def decide(self, input: PolicyRequest) -> PolicyResponse:
        raise NotImplementedError  # Auto-wired at runtime


class PolicyApproverStub(ServerStub):
    """Typed stub for the approval policy approver MCP server."""

    async def set_policy_text(self, input: SetPolicyTextArgs) -> None:
        raise NotImplementedError  # Auto-wired at runtime

    async def approve_proposal(self, input: ApproveProposalArgs) -> None:
        raise NotImplementedError  # Auto-wired at runtime

    async def reject_proposal(self, input: RejectProposalArgs) -> None:
        raise NotImplementedError  # Auto-wired at runtime
