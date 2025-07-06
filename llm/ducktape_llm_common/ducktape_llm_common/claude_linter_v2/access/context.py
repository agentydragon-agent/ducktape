"""Context object for predicate evaluation."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PredicateContext:
    """
    Context provided to predicate functions for evaluation.

    This is a restricted context that provides safe access to
    information about the current operation without allowing
    arbitrary file/network access.
    """

    # Tool information
    tool: str  # Tool name: Write, Edit, MultiEdit, Read, Bash, etc.

    # File information (for file-based tools)
    path: str | None = None  # File path being operated on
    content: str | None = None  # New content (for Write)
    old_content: str | None = None  # Old content (for Edit)

    # Command information (for Bash)
    command: str | None = None  # Command being executed

    # Session information
    session_id: str = "unknown"
    user: str | None = None  # Future: user identification

    # Timing information
    timestamp: datetime = datetime.now()

    # Additional metadata
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Initialize defaults."""
        if self.metadata is None:
            self.metadata = {}

    def glob_match(self, pattern: str) -> bool:
        """
        Check if the current path matches a glob pattern.

        Args:
            pattern: Glob pattern to match against

        Returns:
            True if path matches pattern
        """
        if not self.path:
            return False

        from fnmatch import fnmatch

        return fnmatch(self.path, pattern)

    def is_test_file(self) -> bool:
        """Check if the current file is a test file."""
        if not self.path:
            return False

        test_patterns = [
            "**/test_*.py",
            "**/*_test.py",
            "**/tests/**/*.py",
            "**/test/**/*.py",
        ]

        return any(self.glob_match(pattern) for pattern in test_patterns)

    def is_prod_file(self) -> bool:
        """Check if the current file is a production file."""
        if not self.path:
            return False

        prod_patterns = [
            "*.prod.*",
            "**/prod/**/*",
            "**/production/**/*",
        ]

        return any(self.glob_match(pattern) for pattern in prod_patterns)

    @property
    def file_extension(self) -> str | None:
        """Get the file extension."""
        if not self.path:
            return None

        path = Path(self.path)
        return path.suffix.lstrip(".")

    @property
    def file_name(self) -> str | None:
        """Get the file name without path."""
        if not self.path:
            return None

        return Path(self.path).name

    @property
    def directory(self) -> str | None:
        """Get the directory containing the file."""
        if not self.path:
            return None

        return str(Path(self.path).parent)

    def __repr__(self) -> str:
        """String representation for debugging."""
        parts = [f"tool={self.tool!r}"]

        if self.path:
            parts.append(f"path={self.path!r}")
        if self.command:
            parts.append(f"command={self.command!r}")

        return f"PredicateContext({', '.join(parts)})"
