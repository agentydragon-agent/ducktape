"""Shared types for MCP bridge."""

from enum import StrEnum
from typing import NewType

AgentID = NewType("AgentID", str)


class AgentMode(StrEnum):
    """Agent mode enumeration."""

    LOCAL = "local"
    BRIDGE = "bridge"
