"""Core types for the agent system."""

from typing import NewType

# Agent identifier type (semantic wrapper around str)
AgentID = NewType("AgentID", str)
