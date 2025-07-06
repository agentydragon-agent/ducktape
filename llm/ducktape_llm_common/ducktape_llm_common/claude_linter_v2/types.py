"""Common types for claude-linter-v2."""

from typing import NewType
from uuid import UUID

# Session ID is a UUID-based type for type safety
SessionID = NewType("SessionID", str)  # Actually a UUID string


def parse_session_id(session_id: str) -> SessionID:
    """Parse and validate a session ID."""
    try:
        # Validate it's a proper UUID
        UUID(session_id)
        return SessionID(session_id)
    except ValueError as e:
        raise ValueError(f"Invalid session ID format: {session_id}") from e


def new_session_id() -> SessionID:
    """Generate a new session ID."""
    import uuid

    return SessionID(str(uuid.uuid4()))
