"""Utility functions for the ducktape-llm-common package.

This module provides common utilities for version management,
validation, and other shared functionality.
"""

from pathlib import Path
from typing import Optional, Union

# Import METADATA_VERSION from parent package to avoid circular import
import ducktape_llm_common


def get_metadata_version(path: Optional[Union[str, Path]] = None) -> int:
    """Get the metadata version from a .metadata-version file or return the default.

    Args:
        path: Path to check for .metadata-version file. If None, uses current directory.

    Returns:
        The metadata version number
    """
    if path is None:
        path = Path.cwd()
    else:
        path = Path(path)

    # If path is a file, use its parent directory
    if path.is_file():
        path = path.parent

    # Look for .metadata-version file
    version_file = path / ".metadata-version"
    if version_file.exists():
        try:
            content = version_file.read_text().strip()
            return int(content)
        except (OSError, ValueError):
            # Fall back to default if file is corrupted
            pass

    # Return default version
    return ducktape_llm_common.METADATA_VERSION


def validate_metadata_version(
    version: int, path: Optional[Union[str, Path]] = None
) -> bool:
    """Validate that a metadata version is compatible with the current version.

    Args:
        version: The version to validate
        path: Optional path to check for local version override

    Returns:
        True if the version is compatible, False otherwise
    """
    current_version = get_metadata_version(path)

    # For now, we only support exact version matches
    # In the future, we might support backward compatibility
    return version == current_version


def create_metadata_version_file(
    path: Union[str, Path], version: Optional[int] = None
) -> None:
    """Create a .metadata-version file at the specified path.

    Args:
        path: Directory where to create the file
        version: Version number to write (defaults to METADATA_VERSION)
    """
    path = Path(path)
    if not path.is_dir():
        raise ValueError(f"Path must be a directory: {path}")

    version_file = path / ".metadata-version"
    version_to_write = (
        version if version is not None else ducktape_llm_common.METADATA_VERSION
    )

    version_file.write_text(f"{version_to_write}\n")


# Common validation utilities that will be shared by linters
def is_valid_url_scheme(url: str, allowed_schemes: list[str]) -> bool:
    """Check if a URL has one of the allowed schemes.

    Args:
        url: The URL to check
        allowed_schemes: List of allowed URL schemes

    Returns:
        True if the URL has an allowed scheme, False otherwise
    """
    for scheme in allowed_schemes:
        if url.startswith(f"{scheme}://"):
            return True
    return False


def find_files_with_pattern(
    root_dir: Union[str, Path], pattern: str, exclude_dirs: Optional[list[str]] = None
) -> list[Path]:
    """Find all files matching a pattern, excluding certain directories.

    Args:
        root_dir: Root directory to search
        pattern: Glob pattern to match files
        exclude_dirs: List of directory names to exclude

    Returns:
        List of matching file paths
    """
    root_dir = Path(root_dir)
    exclude_dirs = exclude_dirs or [
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
    ]

    matches = []
    for path in root_dir.rglob(pattern):
        # Check if any parent directory should be excluded
        if any(excluded in path.parts for excluded in exclude_dirs):
            continue
        matches.append(path)

    return matches


# Import enhanced version checking functionality
# Import fix_newlines utilities
from ducktape_llm_common.utils.fix_newlines import fix_newlines_in_file

# Import migration framework
from ducktape_llm_common.utils.migration_framework import (
    BackupManager,
    FileMigrationStep,
    Migration,
    MigrationContext,
    MigrationRunner,
    MigrationStep,
    RenameFileStep,
    UpdateFileContentStep,
    migration_runner,
)
from ducktape_llm_common.utils.version_check import (
    VERSION_HISTORY,
    IncompatibleVersionError,
    VersionError,
    VersionInfo,
    VersionMigrationError,
    VersionMigrator,
    check_version_compatibility,
    ensure_version_file,
    find_version_files,
    get_version_info,
    get_version_report,
    migrator,
    validate_version_strict,
)

__all__ = [
    # Basic version functions
    "get_metadata_version",
    "validate_metadata_version",
    "create_metadata_version_file",
    # Enhanced version functions
    "VersionError",
    "IncompatibleVersionError",
    "VersionMigrationError",
    "VersionInfo",
    "VERSION_HISTORY",
    "get_version_info",
    "check_version_compatibility",
    "validate_version_strict",
    "find_version_files",
    "ensure_version_file",
    "VersionMigrator",
    "migrator",
    "get_version_report",
    # Migration framework
    "MigrationContext",
    "MigrationStep",
    "FileMigrationStep",
    "Migration",
    "BackupManager",
    "MigrationRunner",
    "RenameFileStep",
    "UpdateFileContentStep",
    "migration_runner",
    # Other utilities
    "is_valid_url_scheme",
    "find_files_with_pattern",
    "fix_newlines_in_file",
]
