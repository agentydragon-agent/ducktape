from __future__ import annotations

from typing import Final

from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse
from adgn.mcp._shared.constants import APPROVAL_ADMIN_MOUNT_PREFIX, POLICY_READER_MOUNT_PREFIX
from adgn.mcp.approval_policy.engine import DecideProposalArgs, SetPolicyTextArgs
from adgn.mcp.stubs.server_stubs import ServerStub

READER_SERVER_NAME: Final[str] = POLICY_READER_MOUNT_PREFIX
ADMIN_SERVER_NAME: Final[str] = APPROVAL_ADMIN_MOUNT_PREFIX


class PolicyReaderStub(ServerStub):
    """Typed stub for the approval policy reader MCP server."""

    async def evaluate_policy(self, input: PolicyRequest) -> PolicyResponse:
        raise NotImplementedError  # Auto-wired at runtime


class PolicyApproverStub(ServerStub):
    """Typed stub for the approval policy approver MCP server."""

    async def set_policy_text(self, input: SetPolicyTextArgs) -> None:
        raise NotImplementedError  # Auto-wired at runtime

    async def decide_proposal(self, input: DecideProposalArgs) -> None:
        raise NotImplementedError  # Auto-wired at runtime
