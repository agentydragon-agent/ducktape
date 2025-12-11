"""File filtering utilities using gitignore-style patterns."""

from __future__ import annotations

from collections.abc import Sequence
import fnmatch


def apply_gitignore_patterns(
    file_list: list[str], include: Sequence[str] = (), exclude: Sequence[str] = ()
) -> list[str]:
    """Apply gitignore-style include/exclude patterns to a file list.

    Include patterns are applied first (whitelist), then exclude patterns (blacklist).

    Args:
        file_list: List of file paths to filter
        include: Patterns to include (if specified, only matching files are kept)
        exclude: Patterns to exclude (matching files are removed)

    Returns:
        Filtered list of file paths

    Example:
        >>> apply_gitignore_patterns(
        ...     ["adgn/src/foo.py", "adgn/tests/test.py", "wt/bar.py"],
        ...     include=["adgn/"],
        ...     exclude=["adgn/tests/"]
        ... )
        ["adgn/src/foo.py"]
    """

    def matches_pattern(path: str, pattern: str) -> bool:
        """Check if path matches gitignore-style pattern."""
        # Remove trailing slash from pattern (indicates directory)
        if pattern.endswith("/"):
            pattern = pattern.rstrip("/")
            # For directory patterns, match the directory and everything under it
            return path.startswith(pattern + "/") or path == pattern
        # For file patterns, use fnmatch
        return fnmatch.fnmatch(path, pattern) or path.startswith(pattern + "/")

    def matches_any_pattern(path: str, patterns: Sequence[str]) -> bool:
        """Check if path matches any of the given patterns."""
        return any(matches_pattern(path, pattern) for pattern in patterns)

    result = file_list

    # Apply include patterns (if specified, only keep matching files)
    if include:
        result = [f for f in result if matches_any_pattern(f, include)]

    # Apply exclude patterns (remove matching files)
    if exclude:
        result = [f for f in result if not matches_any_pattern(f, exclude)]

    return result
