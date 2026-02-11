"""Core types for the agent system."""

from typing import Annotated

from pydantic import StringConstraints

# Agent identifier type with validation
# Rules:
# - Must be non-empty (min_length=1)
# - Only lowercase alphanumeric characters and hyphens allowed
# - Must start with alphanumeric character (not hyphen)
# - Safe to use as tool/resource prefix: agent_{id}_tool_name
AgentID = Annotated[str, StringConstraints(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")]
