"""Tests for critic scopes loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.sync import (
    get_specimens_base_path,
    sync_critic_scopes_to_db,
    sync_issues_to_db,
    sync_snapshots_to_db,
)
from adgn.props.db.sync._loader import FilesystemLoader
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ALL_FILES_WITH_ISSUES, CriticScope


@pytest.fixture
def synced_test_db(test_db):
    """Test database with production specimens synced."""
    specimens_dir = get_specimens_base_path()
    with get_session() as session:
        # Sync snapshots, issues, and critic scopes from production specimens
        sync_snapshots_to_db(session, specimens_dir)
        sync_issues_to_db(session, specimens_dir)
        sync_critic_scopes_to_db(session, specimens_dir)
        session.commit()
    return test_db


@pytest.fixture
def loader() -> FilesystemLoader:
    """Create a FilesystemLoader for testing."""
    return FilesystemLoader(get_specimens_base_path())


def test_load_critic_scopes(loader: FilesystemLoader):
    """Test loading critic_scopes.yaml."""
    scopes = loader.load_critic_scopes()

    # Should have scopes for training snapshots
    assert SnapshotSlug("ducktape/2025-12-04-00") in scopes
    assert SnapshotSlug("ducktape/2025-11-20-00") in scopes
    assert SnapshotSlug("crush/2025-08-30-internal_db") in scopes

    # Check structure of one scope
    ducktape_scopes = scopes[SnapshotSlug("ducktape/2025-12-04-00")]
    assert len(ducktape_scopes) > 0
    assert all(isinstance(scope, CriticScope) for scope in ducktape_scopes)

    # Verify scope has required fields (files is set[Path] or "all")
    first_scope = ducktape_scopes[0]
    assert first_scope.files == ALL_FILES_WITH_ISSUES or isinstance(first_scope.files, set)
    if first_scope.files != ALL_FILES_WITH_ISSUES:
        assert len(first_scope.files) > 0


def test_load_critic_scopes_missing_file(tmp_path: Path):
    """Test that missing critic_scopes.yaml raises FileNotFoundError."""
    loader = FilesystemLoader(tmp_path)
    with pytest.raises(FileNotFoundError, match=r"critic_scopes\.yaml is required"):
        loader.load_critic_scopes()


def test_validate_critic_scopes_coverage_catches_missing(tmp_path: Path):
    """Test that validation catches missing expect_caught_from sets."""
    # Create minimal test structure
    test_snapshot_dir = tmp_path / "test-project" / "2025-01-01-00"
    test_snapshot_dir.mkdir(parents=True)

    # Create snapshots.yaml
    (tmp_path / "snapshots.yaml").write_text("""
test-project/2025-01-01-00:
  source:
    vcs: local
    root: "."
  split: train
""")

    # Create critic_scopes.yaml with only ONE scope
    (tmp_path / "critic_scopes.yaml").write_text("""
test-project/2025-01-01-00:
  # Only covering file1.py
  - files: ["src/file1.py"]
""")

    # Create issue with TWO expect_caught_from sets
    (test_snapshot_dir / "test-issue.libsonnet").write_text("""
local I = import 'lib.libsonnet';
I.issue(
  rationale='Test issue with multiple trigger sets',
  filesToRanges={'src/file1.py': [[1, 5]], 'src/file2.py': [[10, 15]]},
  expect_caught_from=[['src/file1.py'], ['src/file2.py']]
)
""")

    # Create lib.libsonnet
    (tmp_path / "lib.libsonnet").write_text("""
{
  issue(rationale, filesToRanges, expect_caught_from=null): {
    rationale: rationale,
    occurrences: [
      {
        files: filesToRanges,
        expect_caught_from: if expect_caught_from != null then expect_caught_from else [std.objectFields(filesToRanges)],
      }
    ],
  },
}
""")

    loader = FilesystemLoader(tmp_path)

    # Should raise ValueError because file2.py scope is missing
    with pytest.raises(ValueError, match="expect_caught_from sets are missing") as exc_info:
        loader.validate_critic_scopes_coverage()

    error_msg = str(exc_info.value)
    assert "test-project/2025-01-01-00" in error_msg
    assert "src/file2.py" in error_msg  # Missing scope


@pytest.mark.slow
def test_snapshot_has_all_expect_caught_from_scopes(loader: FilesystemLoader, synced_test_db):
    """Test that every expect_caught_from set has a corresponding critic scope.

    Iterates over all snapshots in the synced test database.
    A snapshot passes if all its expect_caught_from sets have matching scopes in critic_scopes.yaml.
    """
    critic_scopes = loader.load_critic_scopes()

    # Get all snapshots from database
    with get_session() as session:
        snapshots = session.query(Snapshot).all()
        snapshot_slugs = [s.slug for s in snapshots]

    failures = []

    for snapshot_slug in snapshot_slugs:
        snapshot_scopes = critic_scopes.get(snapshot_slug, [])

        # Get all files for resolution
        all_tps, _ = loader.load_issues_for_snapshot(snapshot_slug)
        all_files = loader._collect_all_files_from_issues(all_tps, [])

        # Build set of scope file sets (resolve "all" sentinel and validate)
        scope_file_sets: set[frozenset[Path]] = set()

        for scope in snapshot_scopes:
            # Resolve scope using the loader's helper
            resolved = loader._resolve_critic_scope(scope, all_files, snapshot_slug)
            scope_file_sets.add(frozenset(resolved))

        # Check all expect_caught_from sets
        missing_sets: list[tuple[str, frozenset[Path]]] = []

        for tp in all_tps:
            for occurrence in tp.occurrences:
                for trigger_set in occurrence.expect_caught_from:
                    trigger_frozenset = frozenset(trigger_set)
                    if trigger_frozenset not in scope_file_sets:
                        missing_sets.append((tp.tp_id, trigger_frozenset))

        # Collect failures for this snapshot
        if missing_sets:
            error_lines = [f"\nSnapshot {snapshot_slug} is missing critic scopes for these expect_caught_from sets:"]
            for tp_id, file_set in missing_sets:
                files_str = ", ".join(str(f) for f in sorted(file_set))
                error_lines.append(f"  - TP {tp_id}: [{files_str}]")
            error_lines.append(f"\nAdd these {len(missing_sets)} scope(s) to critic_scopes.yaml under {snapshot_slug}")
            failures.append("\n".join(error_lines))

    # Report all failures at once
    if failures:
        pytest.fail("\n\n".join(failures))
