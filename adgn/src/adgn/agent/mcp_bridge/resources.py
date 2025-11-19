"""Centralized resource URI constants for agents MCP server."""

# Zero-parameter resource URIs (constants)
AGENTS_LIST = "resource://agents/list"
"""Resource URI for listing all agents."""

APPROVALS_PENDING_GLOBAL = "resource://approvals/pending"
"""Resource URI for global mailbox (all pending approvals)."""

ACTIVE_POLICY = "resource://approval-policy/policy.py"
"""Resource URI for active approval policy."""


# Parameterized resource URIs (functions)
def agent_state(agent_id: str) -> str:
    """Resource URI for agent sampling state."""
    return f"resource://agents/{agent_id}/state"


def agent_approvals_pending(agent_id: str) -> str:
    """Resource URI for pending approvals for an agent."""
    return f"resource://agents/{agent_id}/approvals/pending"


def agent_approvals_history(agent_id: str) -> str:
    """Resource URI for approval history timeline."""
    return f"resource://agents/{agent_id}/approvals/history"


def agent_approval(agent_id: str, call_id: str) -> str:
    """Resource URI for a specific approval."""
    return f"resource://agents/{agent_id}/approvals/{call_id}"


def agent_policy_proposals(agent_id: str) -> str:
    """Resource URI for policy proposals."""
    return f"resource://agents/{agent_id}/policy/proposals"


def policy_proposal(proposal_id: str) -> str:
    """Resource URI for a specific policy proposal."""
    return f"resource://approval-policy/proposals/{proposal_id}"
