"""Display utilities for props CLI commands."""

from __future__ import annotations

from uuid import UUID

SHORT_UUID_LENGTH = 8


def short_uuid(uuid: UUID) -> str:
    """Return first 8 characters of UUID for display."""
    return str(uuid)[:SHORT_UUID_LENGTH]
