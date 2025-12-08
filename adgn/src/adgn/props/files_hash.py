"""File set hashing utilities for cache keys.

Provides deterministic hashing of file sets for database cache lookups.
Used by both CriticScopeDB (for uniqueness) and CriticRun (for cache keys).

IMPORTANT: All scopes (including "all files") must be resolved to actual file sets
before hashing. The DB only stores resolved file lists, never sentinels.
"""

from collections.abc import Iterable
import hashlib
from pathlib import Path


def hash_file_set(files: Iterable[str | Path]) -> str:
    """Calculate SHA256 hash of a resolved file set.

    All scopes must be resolved to actual file paths before calling this function.
    Accepts any collection of str or Path, handles deduplication and sorting.

    Args:
        files: Resolved file paths as any iterable of str or Path

    Returns:
        64-character SHA256 hex digest

    Examples:
        >>> hash_file_set({Path("a.py"), Path("b.py")})
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        >>> hash_file_set(["a.py", "b.py"])  # Same hash
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        >>> hash_file_set(["b.py", "a.py", "a.py"])  # Same hash (sorted, deduplicated)
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    # Deduplicate and sort for deterministic hash
    unique_sorted_files = sorted({str(p) for p in files})
    content = "\n".join(unique_sorted_files).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
