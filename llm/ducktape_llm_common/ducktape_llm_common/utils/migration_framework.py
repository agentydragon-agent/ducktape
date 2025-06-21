"""Migration framework for handling version upgrades.

This module provides utilities and base classes for implementing
metadata version migrations in a structured way.
"""

import json
import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ducktape_llm_common.utils.version_check import (
    VersionMigrationError,
    create_metadata_version_file,
    get_metadata_version,
)

logger = logging.getLogger(__name__)


@dataclass
class MigrationContext:
    """Context information passed to migration handlers."""

    path: Path
    from_version: int
    to_version: int
    backup_path: Optional[Path] = None
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with context information."""
        log_func = getattr(logger, level, logger.info)
        log_func(f"[Migration v{self.from_version}→v{self.to_version}] {message}")


class MigrationStep(ABC):
    """Abstract base class for a single migration step."""

    @abstractmethod
    def description(self) -> str:
        """Return a description of what this step does."""
        pass

    @abstractmethod
    def check(self, context: MigrationContext) -> tuple[bool, Optional[str]]:
        """Check if this step needs to be applied.

        Returns:
            Tuple of (needs_migration, reason_if_not)
        """
        pass

    @abstractmethod
    def apply(self, context: MigrationContext) -> None:
        """Apply the migration step."""
        pass

    def rollback(self, context: MigrationContext) -> None:
        """Rollback the migration step if possible.

        Default implementation does nothing. Override for reversible steps.
        """
        pass


class FileMigrationStep(MigrationStep):
    """Base class for migrations that operate on specific files."""

    def __init__(self, file_pattern: str):
        self.file_pattern = file_pattern

    def find_files(self, context: MigrationContext) -> list[Path]:
        """Find all files matching the pattern."""
        return list(context.path.rglob(self.file_pattern))

    def check(self, context: MigrationContext) -> tuple[bool, Optional[str]]:
        """Check if any matching files exist."""
        files = self.find_files(context)
        if not files:
            return False, f"No files matching {self.file_pattern}"
        return True, None


class Migration(ABC):
    """Abstract base class for a complete version migration."""

    def __init__(self, from_version: int, to_version: int):
        self.from_version = from_version
        self.to_version = to_version
        self._steps: list[MigrationStep] = []

    @abstractmethod
    def description(self) -> str:
        """Return a description of the migration."""
        pass

    @abstractmethod
    def initialize_steps(self) -> None:
        """Initialize the migration steps.

        Subclasses should call add_step() to register steps.
        """
        pass

    def add_step(self, step: MigrationStep) -> None:
        """Add a migration step."""
        self._steps.append(step)

    def check(self, context: MigrationContext) -> list[tuple[MigrationStep, str]]:
        """Check which steps need to be applied.

        Returns:
            List of (step, reason) for steps that need migration
        """
        if not self._steps:
            self.initialize_steps()

        needed_steps = []
        for step in self._steps:
            needs_migration, reason = step.check(context)
            if needs_migration:
                needed_steps.append((step, reason or "Migration needed"))

        return needed_steps

    def apply(self, context: MigrationContext) -> None:
        """Apply all migration steps."""
        if not self._steps:
            self.initialize_steps()

        applied_steps = []
        try:
            for i, step in enumerate(self._steps):
                context.log(f"Step {i + 1}/{len(self._steps)}: {step.description()}")

                if context.dry_run:
                    needs_migration, _ = step.check(context)
                    if needs_migration:
                        context.log("  Would apply (dry run)")
                else:
                    step.apply(context)
                    applied_steps.append(step)
                    context.log("  Applied successfully")

        except Exception as e:
            # Attempt rollback of applied steps
            context.log(f"Migration failed: {e}", level="error")
            if not context.dry_run and applied_steps:
                context.log("Attempting rollback...", level="warning")
                for step in reversed(applied_steps):
                    try:
                        step.rollback(context)
                        context.log(f"  Rolled back: {step.description()}")
                    except Exception as rollback_error:
                        context.log(
                            f"  Rollback failed for {step.description()}: {rollback_error}",
                            level="error",
                        )
            raise VersionMigrationError(f"Migration failed: {e}") from e


class BackupManager:
    """Manages backups during migrations."""

    @staticmethod
    def create_backup(path: Path, version: int) -> Path:
        """Create a backup of the specified path.

        Returns:
            Path to the backup directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f".backup_v{version}_{timestamp}"
        backup_path = path.parent / backup_name / path.name

        # Create backup directory
        backup_path.parent.mkdir(exist_ok=True)

        # Copy the directory
        if path.is_dir():
            shutil.copytree(path, backup_path, dirs_exist_ok=True)
        else:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)

        # Create backup metadata
        metadata_file = backup_path.parent / "backup_metadata.json"
        metadata_file.write_text(
            json.dumps(
                {
                    "original_path": str(path),
                    "version": version,
                    "timestamp": timestamp,
                    "backup_type": "pre_migration",
                },
                indent=2,
            )
        )

        logger.info(f"Created backup at {backup_path}")
        return backup_path

    @staticmethod
    def restore_backup(backup_path: Path, target_path: Path) -> None:
        """Restore from a backup."""
        if not backup_path.exists():
            raise ValueError(f"Backup not found: {backup_path}")

        # Remove current content
        if target_path.exists():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

        # Restore from backup
        if backup_path.is_dir():
            shutil.copytree(backup_path, target_path)
        else:
            shutil.copy2(backup_path, target_path)

        logger.info(f"Restored from backup: {backup_path} → {target_path}")


class MigrationRunner:
    """Runs migrations with proper error handling and backup."""

    def __init__(self):
        self.migrations: dict[tuple[int, int], Migration] = {}

    def register(self, migration: Migration) -> None:
        """Register a migration."""
        key = (migration.from_version, migration.to_version)
        self.migrations[key] = migration

    def can_migrate(self, from_version: int, to_version: int) -> bool:
        """Check if a migration path exists."""
        return (from_version, to_version) in self.migrations

    def get_migration_path(self, from_version: int, to_version: int) -> list[Migration]:
        """Get the migration path between versions.

        Currently only supports direct migrations.
        Future: implement multi-step migration paths.
        """
        key = (from_version, to_version)
        if key in self.migrations:
            return [self.migrations[key]]
        return []

    def run(
        self,
        path: Path,
        target_version: Optional[int] = None,
        dry_run: bool = False,
        create_backup: bool = True,
    ) -> None:
        """Run migration to bring path to target version.

        Args:
            path: Path to migrate
            target_version: Target version (defaults to current package version)
            dry_run: If True, only show what would be done
            create_backup: If True, create backup before migration
        """
        current_version = get_metadata_version(path)

        if target_version is None:
            import ducktape_llm_common

            target_version = ducktape_llm_common.METADATA_VERSION

        if current_version == target_version:
            logger.info(f"Already at version {target_version}")
            return

        # Get migration path
        migrations = self.get_migration_path(current_version, target_version)
        if not migrations:
            raise VersionMigrationError(
                f"No migration path from v{current_version} to v{target_version}"
            )

        # Create backup if requested
        backup_path = None
        if create_backup and not dry_run:
            backup_path = BackupManager.create_backup(path, current_version)

        # Run migrations
        for migration in migrations:
            context = MigrationContext(
                path=path,
                from_version=migration.from_version,
                to_version=migration.to_version,
                backup_path=backup_path,
                dry_run=dry_run,
            )

            logger.info(
                f"{'Would run' if dry_run else 'Running'} migration: "
                f"{migration.description()}"
            )

            # Check what needs to be done
            needed_steps = migration.check(context)
            if not needed_steps:
                logger.info("  No changes needed")
                continue

            logger.info(f"  {len(needed_steps)} steps to apply:")
            for step, reason in needed_steps:
                logger.info(f"    - {step.description()}: {reason}")

            # Apply migration
            migration.apply(context)

            # Update version file
            if not dry_run:
                create_metadata_version_file(path, migration.to_version)
                logger.info(f"Updated version to {migration.to_version}")


# Example migration steps for common scenarios


class RenameFileStep(FileMigrationStep):
    """Migration step that renames files."""

    def __init__(self, old_pattern: str, new_name_func: callable):
        super().__init__(old_pattern)
        self.new_name_func = new_name_func

    def description(self) -> str:
        return f"Rename files matching {self.file_pattern}"

    def apply(self, context: MigrationContext) -> None:
        for old_path in self.find_files(context):
            new_name = self.new_name_func(old_path.name)
            new_path = old_path.parent / new_name
            old_path.rename(new_path)
            context.log(f"  Renamed: {old_path.name} → {new_name}")


class UpdateFileContentStep(FileMigrationStep):
    """Migration step that updates file contents."""

    def __init__(self, file_pattern: str, update_func: callable):
        super().__init__(file_pattern)
        self.update_func = update_func

    def description(self) -> str:
        return f"Update content of files matching {self.file_pattern}"

    def apply(self, context: MigrationContext) -> None:
        for file_path in self.find_files(context):
            content = file_path.read_text()
            new_content = self.update_func(content)
            if new_content != content:
                file_path.write_text(new_content)
                context.log(f"  Updated: {file_path.relative_to(context.path)}")


# Global migration runner instance
migration_runner = MigrationRunner()


__all__ = [
    "MigrationContext",
    "MigrationStep",
    "FileMigrationStep",
    "Migration",
    "BackupManager",
    "MigrationRunner",
    "RenameFileStep",
    "UpdateFileContentStep",
    "migration_runner",
]
