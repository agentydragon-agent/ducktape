"""Shared types for MCP bridge."""

from enum import StrEnum

from adgn.agent.types import AgentID

__all__ = ["AgentID", "AgentMode"]


class AgentMode(StrEnum):
    """Agent mode enumeration."""

    LOCAL = "local"
    BRIDGE = "bridge"
