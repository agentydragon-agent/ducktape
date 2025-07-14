"""Common types for claude-linter-v2."""

from typing import NewType
from uuid import UUID

# Session ID is a UUID-based type for type safety
SessionID = NewType("SessionID", UUID)
