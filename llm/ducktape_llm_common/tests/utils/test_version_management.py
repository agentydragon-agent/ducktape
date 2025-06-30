"""Tests for the version management system."""

import tempfile
from pathlib import Path

import pytest

from ducktape_llm_common import METADATA_VERSION
from ducktape_llm_common.utils import (
    IncompatibleVersionError,
    VersionInfo,
    VersionMigrationError,
    VersionMigrator,
    check_version_compatibility,
    create_metadata_version_file,
    ensure_version_file,
    find_version_files,
    get_metadata_version,
    get_version_info,
    get_version_report,
    validate_metadata_version,
    validate_version_strict,
)


class TestBasicVersionFunctions:
    """Test basic version management functions."""

    def test_get_metadata_version_default(self):
        """Test getting default metadata version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            version = get_metadata_version(tmpdir)
            assert version == METADATA_VERSION

    def test_get_metadata_version_from_file(self):
        """Test reading version from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = Path(tmpdir) / ".metadata-version"
            version_file.write_text("2\n")

            version = get_metadata_version(tmpdir)
            assert version == 2

    def test_create_metadata_version_file(self):
        """Test creating version file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            create_metadata_version_file(path)

            version_file = path / ".metadata-version"
            assert version_file.exists()
            assert version_file.read_text().strip() == str(METADATA_VERSION)

    def test_create_metadata_version_file_custom(self):
        """Test creating version file with custom version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            create_metadata_version_file(path, version=3)

            version_file = path / ".metadata-version"
            assert version_file.read_text().strip() == "3"

    def test_validate_metadata_version(self):
        """Test version validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Current version should be valid
            assert validate_metadata_version(METADATA_VERSION, tmpdir)

            # Different version should be invalid
            assert not validate_metadata_version(999, tmpdir)


class TestEnhancedVersionFunctions:
    """Test enhanced version management functions."""

    def test_get_version_info(self):
        """Test getting version information."""
        info = get_version_info(1)
        assert info is not None
        assert isinstance(info, VersionInfo)
        assert info.version == 1
        assert info.description
        assert info.introduced
        assert isinstance(info.changes, list)

    def test_get_version_info_unknown(self):
        """Test getting info for unknown version."""
        info = get_version_info(999)
        assert info is None

    def test_check_version_compatibility(self):
        """Test version compatibility checking."""
        # Same version is compatible
        compatible, reason = check_version_compatibility(1, 1)
        assert compatible
        assert reason is None

        # Unknown versions are not compatible
        compatible, reason = check_version_compatibility(1, 999)
        assert not compatible
        assert "Unknown target version" in reason

    def test_validate_version_strict(self):
        """Test strict version validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            create_metadata_version_file(path, version=1)

            # Should not raise for matching version
            validate_version_strict(path, expected_version=1)

            # Should raise for mismatched version
            with pytest.raises(IncompatibleVersionError) as exc_info:
                validate_version_strict(path, expected_version=2)

            assert exc_info.value.found_version == 1
            assert exc_info.value.expected_version == 2

    def test_find_version_files(self):
        """Test finding version files in directory tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create version files in subdirectories
            (root / "project1").mkdir()
            create_metadata_version_file(root / "project1", version=1)

            (root / "project2").mkdir()
            create_metadata_version_file(root / "project2", version=2)

            (root / "nested" / "project3").mkdir(parents=True)
            create_metadata_version_file(root / "nested" / "project3", version=1)

            # Find all version files
            version_files = find_version_files(root)
            assert len(version_files) == 3

            # Check versions
            versions_by_path = {str(path.name): version for path, version in version_files}
            assert versions_by_path["project1"] == 1
            assert versions_by_path["project2"] == 2
            assert versions_by_path["project3"] == 1

    def test_ensure_version_file(self):
        """Test ensuring version file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            # First call should create file
            created = ensure_version_file(path)
            assert created
            assert (path / ".metadata-version").exists()

            # Second call should not modify existing file
            created = ensure_version_file(path)
            assert not created

            # Force flag should overwrite
            created = ensure_version_file(path, version=2, force=True)
            assert created
            assert get_metadata_version(path) == 2


class TestVersionMigration:
    """Test version migration functionality."""

    def test_version_migrator_registration(self):
        """Test registering migrations."""
        migrator = VersionMigrator()

        def dummy_migration(path):
            pass

        migrator.register_migration(1, 2, dummy_migration)
        assert migrator.can_migrate(1, 2)
        assert not migrator.can_migrate(2, 3)

    def test_version_migrator_migrate(self):
        """Test performing migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            create_metadata_version_file(path, version=1)

            migrator = VersionMigrator()

            # Track if migration was called
            migration_called = False

            def test_migration(migration_path):
                nonlocal migration_called
                migration_called = True
                assert migration_path == path

            migrator.register_migration(1, 2, test_migration)

            # Perform migration
            migrator.migrate(path, from_version=1, to_version=2, backup=False)

            assert migration_called
            assert get_metadata_version(path) == 2

    def test_version_migrator_no_path(self):
        """Test migration with no migration path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)

            migrator = VersionMigrator()

            with pytest.raises(VersionMigrationError) as exc_info:
                migrator.migrate(path, from_version=1, to_version=2)

            assert "No migration path" in str(exc_info.value)


class TestVersionReport:
    """Test version reporting functionality."""

    def test_get_version_report(self):
        """Test generating version report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create mixed version files
            (root / "v1_project").mkdir()
            create_metadata_version_file(root / "v1_project", version=1)

            (root / "v2_project").mkdir()
            create_metadata_version_file(root / "v2_project", version=2)

            (root / "another_v1").mkdir()
            create_metadata_version_file(root / "another_v1", version=1)

            # Generate report
            report = get_version_report(root)

            assert report["current_version"] == METADATA_VERSION
            assert report["total_versioned_paths"] == 3
            assert report["version_distribution"] == {1: 2, 2: 1}

            # Check all versions are listed
            assert len(report["all_versions"]) == 3
