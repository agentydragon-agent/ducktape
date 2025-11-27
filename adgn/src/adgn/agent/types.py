"""Core types for the agent system."""

import re
from typing import Annotated

from pydantic import AfterValidator

# AgentID validation: lowercase alphanumeric + hyphen, must start with alphanumeric
_AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _validate_agent_id(v: str) -> str:
    """Validate agent ID format.

    Rules:
    - Must be non-empty
    - Only lowercase alphanumeric characters and hyphens allowed
    - Must start with alphanumeric character (not hyphen)
    - Safe to use as tool/resource prefix: agent_{id}_tool_name
    """
    if not v:
        raise ValueError("Agent ID cannot be empty")
    if not _AGENT_ID_PATTERN.match(v):
        raise ValueError(
            f"Invalid agent ID: {v!r}. Must be lowercase alphanumeric + hyphen, "
            "starting with alphanumeric character."
        )
    return v


# Agent identifier type with validation
# Usage: AgentID (in type hints) or AgentID.__metadata__[0] for validator
AgentID = Annotated[str, AfterValidator(_validate_agent_id)]
