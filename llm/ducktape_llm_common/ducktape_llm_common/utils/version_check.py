"""Enhanced version management utilities for ducktape-llm-common.

This module provides comprehensive version checking, validation, and migration
utilities for managing metadata structure versions across the codebase.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

# Import METADATA_VERSION from parent package
import ducktape_llm_common
from ducktape_llm_common.utils import (
    create_metadata_version_file,
    get_metadata_version,
)

logger = logging.getLogger(__name__)


class VersionError(Exception):
    """Base exception for version-related errors."""

    pass


class IncompatibleVersionError(VersionError):
    """Raised when encountering an incompatible metadata version."""

    def __init__(
        self, found_version: int, expected_version: int, path: Optional[Path] = None
    ):
        self.found_version = found_version
        self.expected_version = expected_version
        self.path = path
        message = (
            f"Incompatible metadata version {found_version} "
            f"(expected {expected_version})"
        )
        if path:
            message += f" at {path}"
        super().__init__(message)


class VersionMigrationError(VersionError):
    """Raised when version migration fails."""

    pass


@dataclass
class VersionInfo:
    """Detailed information about a metadata version."""

    version: int
    description: str
    introduced: str  # ISO date when this version was introduced
    changes: list[str]
    compatible_with: list[int]  # List of versions this is compatible with

    def is_compatible_with(self, other_version: int) -> bool:
        """Check if this version is compatible with another version."""
        return other_version in self.compatible_with or other_version == self.version


# Version history and migration information
VERSION_HISTORY: dict[int, VersionInfo] = {
    1: VersionInfo(
        version=1,
        description="Initial metadata structure version",
        introduced="2024-01-20",
        changes=[
            "Basic URL validation support",
            "Initial metadata structure for work tracking",
            "Support for .metadata-version files",
        ],
        compatible_with=[],  # Version 1 is only compatible with itself
    ),
}


def get_version_info(version: int) -> Optional[VersionInfo]:
    """Get detailed information about a specific version.

    Args:
        version: The version number to get info for

    Returns:
        VersionInfo object or None if version not found
    """
    return VERSION_HISTORY.get(version)


def check_version_compatibility(
    source_version: int, target_version: int
) -> tuple[bool, Optional[str]]:
    """Check if two versions are compatible.

    Args:
        source_version: The source/current version
        target_version: The target/required version

    Returns:
        Tuple of (is_compatible, reason_if_not)
    """
    if source_version == target_version:
        return True, None

    source_info = get_version_info(source_version)
    target_info = get_version_info(target_version)

    if not source_info:
        return False, f"Unknown source version: {source_version}"
    if not target_info:
        return False, f"Unknown target version: {target_version}"

    if target_info.is_compatible_with(source_version):
        return True, None
    if source_info.is_compatible_with(target_version):
        return True, None

    return False, (
        f"Version {source_version} is not compatible with {target_version}. "
        f"Migration may be required."
    )


def validate_version_strict(
    path: Union[str, Path], expected_version: Optional[int] = None
) -> None:
    """Strictly validate the metadata version at a path.

    This function raises an exception if the version is incompatible.

    Args:
        path: Path to check for version
        expected_version: Expected version (defaults to METADATA_VERSION)

    Raises:
        IncompatibleVersionError: If version is incompatible
    """
    path = Path(path)
    expected = expected_version or ducktape_llm_common.METADATA_VERSION
    found = get_metadata_version(path)

    if found != expected:
        raise IncompatibleVersionError(found, expected, path)


def find_version_files(
    root_dir: Union[str, Path], exclude_dirs: Optional[list[str]] = None
) -> list[tuple[Path, int]]:
    """Find all .metadata-version files in a directory tree.

    Args:
        root_dir: Root directory to search
        exclude_dirs: Directories to exclude from search

    Returns:
        List of (path, version) tuples
    """
    root_dir = Path(root_dir)
    exclude_dirs = exclude_dirs or [
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
    ]

    version_files = []
    for version_file in root_dir.rglob(".metadata-version"):
        # Check if in excluded directory
        if any(excluded in version_file.parts for excluded in exclude_dirs):
            continue

        try:
            version = int(version_file.read_text().strip())
            version_files.append((version_file.parent, version))
        except (OSError, ValueError) as e:
            logger.warning(f"Invalid version file at {version_file}: {e}")

    return version_files


def ensure_version_file(
    path: Union[str, Path], version: Optional[int] = None, force: bool = False
) -> bool:
    """Ensure a .metadata-version file exists at the specified path.

    Args:
        path: Directory to ensure has version file
        version: Version to use (defaults to METADATA_VERSION)
        force: If True, overwrite existing file

    Returns:
        True if file was created/updated, False if already existed
    """
    path = Path(path)
    version_file = path / ".metadata-version"
    version_to_write = version or ducktape_llm_common.METADATA_VERSION

    if version_file.exists() and not force:
        existing_version = get_metadata_version(path)
        if existing_version == version_to_write:
            return False

    create_metadata_version_file(path, version_to_write)
    return True


class VersionMigrator:
    """Handles migration between metadata versions."""

    def __init__(self):
        self.migrations: dict[tuple[int, int], Callable[[Path], None]] = {}

    def register_migration(
        self, from_version: int, to_version: int, migration_func: Callable[[Path], None]
    ) -> None:
        """Register a migration function for a version transition.

        Args:
            from_version: Source version
            to_version: Target version
            migration_func: Function that performs the migration
        """
        self.migrations[(from_version, to_version)] = migration_func

    def can_migrate(self, from_version: int, to_version: int) -> bool:
        """Check if a migration path exists between versions."""
        return (from_version, to_version) in self.migrations

    def migrate(
        self, path: Path, from_version: int, to_version: int, backup: bool = True
    ) -> None:
        """Perform a version migration.

        Args:
            path: Path to migrate
            from_version: Current version
            to_version: Target version
            backup: Whether to create a backup before migration

        Raises:
            VersionMigrationError: If migration fails
        """
        migration_key = (from_version, to_version)
        if migration_key not in self.migrations:
            raise VersionMigrationError(
                f"No migration path from version {from_version} to {to_version}"
            )

        if backup:
            self._create_backup(path, from_version)

        try:
            migration_func = self.migrations[migration_key]
            migration_func(path)

            # Update version file
            create_metadata_version_file(path, to_version)

            logger.info(
                f"Successfully migrated {path} from version {from_version} "
                f"to {to_version}"
            )
        except Exception as e:
            raise VersionMigrationError(f"Migration failed for {path}: {e}") from e

    def _create_backup(self, path: Path, version: int) -> Path:
        """Create a backup of the path before migration."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f".backup_v{version}_{timestamp}"
        backup_path = path.parent / backup_name

        # For now, just create a marker file
        # In a real implementation, this would copy the entire directory
        marker_file = backup_path / "BACKUP_INFO.json"
        marker_file.parent.mkdir(exist_ok=True)
        marker_file.write_text(
            json.dumps(
                {
                    "original_path": str(path),
                    "version": version,
                    "timestamp": timestamp,
                    "note": "Backup created before version migration",
                },
                indent=2,
            )
        )

        return backup_path


# Global migrator instance
migrator = VersionMigrator()


def get_version_report(root_dir: Union[str, Path]) -> dict[str, Any]:
    """Generate a comprehensive version report for a directory tree.

    Args:
        root_dir: Root directory to analyze

    Returns:
        Dictionary containing version statistics and details
    """
    root_dir = Path(root_dir)
    version_files = find_version_files(root_dir)

    # Collect statistics
    version_counts: dict[int, int] = {}
    incompatible_paths: list[dict[str, Any]] = []

    current_version = ducktape_llm_common.METADATA_VERSION

    for path, version in version_files:
        version_counts[version] = version_counts.get(version, 0) + 1

        compatible, reason = check_version_compatibility(version, current_version)
        if not compatible:
            incompatible_paths.append(
                {"path": str(path), "version": version, "reason": reason}
            )

    return {
        "current_version": current_version,
        "total_versioned_paths": len(version_files),
        "version_distribution": version_counts,
        "incompatible_paths": incompatible_paths,
        "all_versions": [
            {"path": str(path), "version": version} for path, version in version_files
        ],
    }


__all__ = [
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
]
