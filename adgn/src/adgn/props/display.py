"""Display utilities for props CLI commands."""

from __future__ import annotations

from uuid import UUID

# Display constants
SHORT_UUID_LENGTH = 8
SHORT_SHA_LENGTH = 6


def short_uuid(uuid: UUID) -> str:
    """Return shortened UUID for display (first 8 characters).

    Args:
        uuid: UUID to shorten

    Returns:
        First 8 characters of the UUID string (e.g., "a1b2c3d4")
    """
    return str(uuid)[:SHORT_UUID_LENGTH]


def short_sha(sha: str) -> str:
    """Return shortened SHA256 hash for display (first 6 characters).

    Args:
        sha: SHA256 hash string to shorten

    Returns:
        First 6 characters of the SHA string
    """
    return sha[:SHORT_SHA_LENGTH]
