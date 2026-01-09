"""Registry token generation for agents.

Generates tokens that allow agents to push images to their namespace
in the registry. Tokens encode the agent_run_id for ACL enforcement.
"""

from __future__ import annotations

import secrets
from uuid import UUID


def generate_registry_token(agent_run_id: UUID) -> str:
    """Generate a registry token for an agent.

    Token format: "agent_{agent_run_id}_{secret}"

    The agent_run_id is embedded in the token for namespace derivation.
    The secret provides unpredictability (agents can't forge other agents' tokens).

    Args:
        agent_run_id: UUID of the agent run

    Returns:
        Token string for Authorization header
    """
    secret = secrets.token_hex(16)
    return f"agent_{agent_run_id}_{secret}"


def get_agent_namespace(agent_run_id: UUID) -> str:
    """Get the registry namespace for an agent.

    Agents can only push to their namespace: agent-{short_uuid}/*

    Args:
        agent_run_id: UUID of the agent run

    Returns:
        Namespace string (e.g., "agent-a1b2c3d4")
    """
    short_id = str(agent_run_id).split("-")[0]
    return f"agent-{short_id}"
