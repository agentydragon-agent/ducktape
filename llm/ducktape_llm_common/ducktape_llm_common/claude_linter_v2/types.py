"""Common types for claude-linter-v2."""

from typing import NewType
from uuid import UUID

# Session ID is a UUID-based type for type safety
SessionID = NewType("SessionID", UUID)


def parse_session_id(session_id_str: str) -> SessionID:
    """Parse a session ID string into a SessionID."""
    return SessionID(UUID(session_id_str))
