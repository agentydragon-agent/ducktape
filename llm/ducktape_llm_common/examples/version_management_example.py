#!/usr/bin/env python3
"""Example demonstrating the version management system."""

import tempfile
from pathlib import Path

from ducktape_llm_common import METADATA_VERSION
from ducktape_llm_common.utils import (
    IncompatibleVersionError,
    create_metadata_version_file,
    ensure_version_file,
    find_version_files,
    get_metadata_version,
    get_version_info,
    get_version_report,
    migrator,
    validate_version_strict,
)


def demo_basic_usage():
    """Demonstrate basic version management."""
    print("=== Basic Version Management Demo ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "my_project"
        project_path.mkdir()

        # Check default version
        version = get_metadata_version(project_path)
        print(f"Default version (no file): {version}")

        # Create version file
        ensure_version_file(project_path)
        print(f"Created .metadata-version file at {project_path}")

        # Read version from file
        version = get_metadata_version(project_path)
        print(f"Version from file: {version}")

        # Show file contents
        version_file = project_path / ".metadata-version"
        print(f"File contents: {version_file.read_text().strip()!r}")
        print()


def demo_version_info():
    """Demonstrate version information retrieval."""
    print("=== Version Information Demo ===\n")

    # Get info about current version
    info = get_version_info(METADATA_VERSION)
    if info:
        print(f"Version {info.version}: {info.description}")
        print(f"Introduced: {info.introduced}")
        print("Changes:")
        for change in info.changes:
            print(f"  - {change}")
    print()


def demo_version_validation():
    """Demonstrate version validation."""
    print("=== Version Validation Demo ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create projects with different versions
        v1_project = Path(tmpdir) / "v1_project"
        v1_project.mkdir()
        create_metadata_version_file(v1_project, version=1)

        v2_project = Path(tmpdir) / "v2_project"
        v2_project.mkdir()
        create_metadata_version_file(v2_project, version=2)

        # Try validating each
        for project in [v1_project, v2_project]:
            try:
                validate_version_strict(project, expected_version=1)
                print(f"✓ {project.name} is compatible with version 1")
            except IncompatibleVersionError as e:
                print(f"✗ {project.name} incompatible: {e}")
        print()


def demo_version_discovery():
    """Demonstrate finding version files in a project tree."""
    print("=== Version Discovery Demo ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create a project structure
        projects = [
            ("frontend", 1),
            ("backend", 1),
            ("legacy/old_service", 1),
            ("experimental/new_feature", 2),
        ]

        for project_path, version in projects:
            full_path = root / project_path
            full_path.mkdir(parents=True)
            create_metadata_version_file(full_path, version=version)

        # Find all version files
        version_files = find_version_files(root)
        print(f"Found {len(version_files)} versioned directories:")
        for path, version in sorted(version_files):
            relative_path = path.relative_to(root)
            print(f"  {relative_path}: version {version}")
        print()


def demo_version_report():
    """Demonstrate comprehensive version reporting."""
    print("=== Version Report Demo ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create mixed version structure
        structure = [
            ("services/auth", 1),
            ("services/api", 1),
            ("services/web", 1),
            ("tools/linter", 1),
            ("tools/migrator", 2),
            ("experimental/ai", 2),
        ]

        for path, version in structure:
            full_path = root / path
            full_path.mkdir(parents=True)
            create_metadata_version_file(full_path, version=version)

        # Generate report
        report = get_version_report(root)

        print(f"Version Report for {root.name}")
        print(f"Current package version: {report['current_version']}")
        print(f"Total versioned paths: {report['total_versioned_paths']}")
        print(f"Version distribution: {report['version_distribution']}")

        if report["incompatible_paths"]:
            print("\nIncompatible paths:")
            for item in report["incompatible_paths"]:
                path = Path(item["path"]).relative_to(root)
                print(f"  {path}: v{item['version']} - {item['reason']}")
        else:
            print("\nAll paths are compatible!")
        print()


def demo_migration():
    """Demonstrate version migration."""
    print("=== Version Migration Demo ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir) / "migrating_project"
        project.mkdir()

        # Start with version 1
        create_metadata_version_file(project, version=1)
        print("Created project at version 1")

        # Define a simple migration
        def migrate_1_to_2(path):
            """Migrate from version 1 to 2."""
            print(f"  Migrating {path} from v1 to v2...")
            # In a real migration, you would:
            # - Update file formats
            # - Convert data structures
            # - etc.
            print("  Migration complete!")

        # Register the migration
        migrator.register_migration(1, 2, migrate_1_to_2)

        # Check if migration is possible
        if migrator.can_migrate(1, 2):
            print("Migration path available from v1 to v2")

            # Perform migration
            migrator.migrate(project, from_version=1, to_version=2, backup=False)

            # Verify new version
            new_version = get_metadata_version(project)
            print(f"Project now at version {new_version}")
        print()


def main():
    """Run all demonstrations."""
    print("Ducktape LLM Common - Version Management Examples")
    print("=" * 50)
    print()

    demo_basic_usage()
    demo_version_info()
    demo_version_validation()
    demo_version_discovery()
    demo_version_report()
    demo_migration()

    print("Demo complete!")


if __name__ == "__main__":
    main()
