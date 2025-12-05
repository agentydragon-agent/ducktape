"""File set hashing utilities for cache keys.

Provides deterministic hashing of file sets for database cache lookups.
Used by both CriticScopeDB (for uniqueness) and CriticRun (for cache keys).
"""

import hashlib
from pathlib import Path

from adgn.props.models.critic_scopes import ALL_FILES_WITH_ISSUES, CriticScopeSpec


def hash_critic_scope_files(files: CriticScopeSpec) -> str:
    """Calculate SHA256 hash of critic scope files for uniqueness/cache lookup.

    Ensures deterministic hashing across Python runs by:
    - Using special token for "all" sentinel
    - Sorting file paths for set[Path] case

    Args:
        files: CriticScopeSpec (set[Path] or "all" sentinel)

    Returns:
        64-character SHA256 hex digest

    Examples:
        >>> hash_critic_scope_files({Path("a.py"), Path("b.py")})
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        >>> hash_critic_scope_files(ALL_FILES_WITH_ISSUES)
        '...'  # Deterministic hash for sentinel
    """
    if files == ALL_FILES_WITH_ISSUES:
        # Special case for "all" sentinel
        return hashlib.sha256(b"__ALL_FILES_WITH_ISSUES__").hexdigest()

    # Sort paths for deterministic hash
    sorted_files = sorted(str(p) for p in files)
    content = "\n".join(sorted_files).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def hash_file_set(files: set[Path]) -> str:
    """Calculate SHA256 hash of a plain file set (no sentinel support).

    Convenience wrapper for hashing plain file sets without CriticScopeSpec
    union type. Used by CriticRun for cache keys.

    Args:
        files: Set of file paths

    Returns:
        64-character SHA256 hex digest

    Examples:
        >>> hash_file_set({Path("a.py"), Path("b.py")})
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    sorted_files = sorted(str(p) for p in files)
    content = "\n".join(sorted_files).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
