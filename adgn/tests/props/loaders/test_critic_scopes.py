"""Tests for critic scopes loading and per-file example generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from adgn.props.ids import SnapshotSlug
from adgn.props.loaders.filesystem import FilesystemLoader
from adgn.props.models.critic_scopes import ALL_FILES_WITH_ISSUES, CriticScope
from adgn.props.snapshot_registry import SnapshotRegistry
from adgn.props.splits import Split

# Module-level constant for specimens directory (used by loader fixture)
SPECIMENS_DIR = Path(__file__).parent.parent.parent.parent / "src" / "adgn" / "props" / "specimens"


def pytest_generate_tests(metafunc):
    """Generate parametrized tests for all snapshots (for snapshot_slug parameter)."""
    if "snapshot_slug" in metafunc.fixturenames:
        registry = SnapshotRegistry.from_package_resources()
        metafunc.parametrize("snapshot_slug", registry.snapshot_slugs, ids=lambda slug: str(slug))


@pytest.fixture
def loader() -> FilesystemLoader:
    """Create a FilesystemLoader for testing."""
    return FilesystemLoader(SPECIMENS_DIR)


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
    with pytest.raises(FileNotFoundError, match="critic_scopes.yaml is required"):
        loader.load_critic_scopes()


@pytest.mark.slow
def test_get_per_file_examples_for_split_with_scopes(loader: FilesystemLoader):
    """Test generating per-file examples using defined scopes.

    Note: This test loads all training snapshots and evaluates Jsonnet, which can be slow.
    """
    examples = loader.get_per_file_examples_for_split(Split.TRAIN)

    # Should have multiple examples
    assert len(examples) > 0

    # Group by snapshot
    by_snapshot: dict[SnapshotSlug, list] = {}
    for ex in examples:
        by_snapshot.setdefault(ex.snapshot_slug, []).append(ex)

    # Should have multiple snapshots
    assert len(by_snapshot) > 0

    # Check one snapshot in detail
    slug = SnapshotSlug("ducktape/2025-12-04-00")
    if slug in by_snapshot:
        snapshot_examples = by_snapshot[slug]
        assert len(snapshot_examples) > 1, f"Expected multiple examples for {slug}"

        # Last example should be full-snapshot (terminal metric)
        full_example = snapshot_examples[-1]
        all_tps, all_fps = loader.load_issues_for_snapshot(slug)
        all_files = loader._collect_all_files_from_issues(all_tps, all_fps)
        assert full_example.targeted_files == frozenset(all_files), f"Last example for {slug} should target all files"

        # Other examples should target subsets
        for ex in snapshot_examples[:-1]:
            assert len(ex.targeted_files) <= len(all_files), (
                "Scoped example shouldn't have more files than full snapshot"
            )


def test_get_per_file_examples_fallback_no_scopes(tmp_path: Path):
    """Test fallback to per-file examples when no scopes defined."""
    # Create a minimal test snapshot structure
    test_snapshot_dir = tmp_path / "test-project" / "2025-01-01-00"
    test_snapshot_dir.mkdir(parents=True)

    # Create snapshots.yaml
    snapshots_yaml = tmp_path / "snapshots.yaml"
    snapshots_yaml.write_text(
        """
test-project/2025-01-01-00:
  source:
    vcs: local
    root: "."
  split: train
"""
    )

    # Create empty critic_scopes.yaml (triggers fallback for this snapshot)
    critic_scopes_yaml = tmp_path / "critic_scopes.yaml"
    critic_scopes_yaml.write_text("{}\n")

    # Create a simple issue file
    issue_file = test_snapshot_dir / "test-issue.libsonnet"
    issue_file.write_text(
        """
local I = import 'lib.libsonnet';
I.issue(
  rationale='Test issue',
  filesToRanges={'src/test.py': [[1, 5]]},
)
"""
    )

    # Create lib.libsonnet in the specimens directory
    lib_file = tmp_path / "lib.libsonnet"
    lib_file.write_text(
        """
{
  issue(rationale, filesToRanges): {
    rationale: rationale,
    occurrences: [
      {
        files: filesToRanges,
        expect_caught_from: [std.objectFields(filesToRanges)],
      }
    ],
  },
}
"""
    )

    loader = FilesystemLoader(tmp_path)
    examples = loader.get_per_file_examples_for_split(Split.TRAIN)

    # Should have per-file examples + full snapshot
    assert len(examples) >= 2  # At least 1 per-file + 1 full


@pytest.mark.slow
def test_explicit_file_scopes(loader: FilesystemLoader):
    """Test that explicit file scopes are loaded correctly."""
    scopes = loader.load_critic_scopes()

    # Get a snapshot
    slug = SnapshotSlug("ducktape/2025-12-04-00")
    snapshot_scopes = scopes.get(slug, [])

    # Should have explicit file scopes (not wildcards)
    assert len(snapshot_scopes) > 0
    for scope in snapshot_scopes:
        if scope.files != ALL_FILES_WITH_ISSUES:
            # Should be set[Path]
            assert isinstance(scope.files, set)
            assert all(isinstance(f, Path) for f in scope.files)

    # Generate examples
    examples = loader.get_per_file_examples_for_split(Split.TRAIN)
    ducktape_examples = [ex for ex in examples if ex.snapshot_slug == slug]

    # Should have examples from scopes
    assert len(ducktape_examples) > 0


@pytest.mark.slow
def test_training_example_has_catchable_tps(loader: FilesystemLoader):
    """Test that training examples only include catchable TPs."""
    examples = loader.get_per_file_examples_for_split(Split.TRAIN)

    for ex in examples:
        # Each TP should be catchable from the targeted files
        for tp in ex.true_positives:
            catchable = False
            for occurrence in tp.occurrences:
                for trigger_set in occurrence.expect_caught_from:
                    if trigger_set <= ex.targeted_files:
                        catchable = True
                        break
                if catchable:
                    break
            assert catchable, f"TP {tp.tp_id} in example with files {ex.targeted_files} should be catchable"


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
def test_snapshot_has_all_expect_caught_from_scopes(loader: FilesystemLoader, snapshot_slug: SnapshotSlug):
    """Test that every expect_caught_from set has a corresponding critic scope.

    This test is parametrized over all snapshots via pytest_generate_tests hook.
    A snapshot passes if all its expect_caught_from sets have matching scopes in critic_scopes.yaml.
    """
    critic_scopes = loader.load_critic_scopes()
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

    # Report missing sets clearly
    if missing_sets:
        error_lines = [f"\nSnapshot {snapshot_slug} is missing critic scopes for these expect_caught_from sets:"]
        for tp_id, file_set in missing_sets:
            files_str = ", ".join(str(f) for f in sorted(file_set))
            error_lines.append(f"  - TP {tp_id}: [{files_str}]")
        error_lines.append(f"\nAdd these {len(missing_sets)} scope(s) to critic_scopes.yaml under {snapshot_slug}")
        pytest.fail("\n".join(error_lines))


@pytest.mark.slow
def test_per_file_examples_include_terminal_metric(loader: FilesystemLoader):
    """Test that full-snapshot example is always included as last item."""
    examples = loader.get_per_file_examples_for_split(Split.TRAIN)

    # Group by snapshot
    by_snapshot: dict[SnapshotSlug, list] = {}
    for ex in examples:
        by_snapshot.setdefault(ex.snapshot_slug, []).append(ex)

    for slug, snapshot_examples in by_snapshot.items():
        # Get all files for this snapshot
        all_tps, all_fps = loader.load_issues_for_snapshot(slug)
        all_files = loader._collect_all_files_from_issues(all_tps, all_fps)

        # Last example should have all files
        last_example = snapshot_examples[-1]
        assert last_example.targeted_files == frozenset(all_files), (
            f"Last example for {slug} should be full-snapshot (terminal metric)"
        )
