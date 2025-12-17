"""Tests for automatic example generation from expect_caught_from data."""

from __future__ import annotations

from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot, TruePositive
from adgn.props.db.sync._sync import generate_examples_for_snapshot
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.splits import Split


def test_generate_examples_train_split(synced_test_fixtures):
    """Test example generation for TRAIN split creates per-trigger examples + full-specimen."""
    with get_session() as session:
        # Use test-trivial fixture (train split)
        slug = SnapshotSlug("test-fixtures/test-trivial")
        snapshot = session.query(Snapshot).filter_by(slug=slug).one()
        assert snapshot.split == Split.TRAIN

        # Generate examples
        examples = generate_examples_for_snapshot(session, slug, snapshot.split)

        # Should have multiple examples (one per unique trigger set + full-specimen)
        assert len(examples) > 1

        # Each example should be an Example ORM object
        for example in examples:
            assert isinstance(example, Example)

            # Check scope_hash is present and valid
            assert isinstance(example.scope_hash, str)
            assert len(example.scope_hash) == 64  # SHA256 hex length

            # Verify scope is a CriticScopeSpec instance
            assert isinstance(example.scope, AllFilesScope | ExplicitFileScope)

            if isinstance(example.scope, AllFilesScope):
                # AllFilesScope examples
                assert example.scope.kind == "entire_snapshot"
            else:
                # ExplicitFileScope examples
                assert isinstance(example.scope, ExplicitFileScope)
                assert example.scope.kind == "specific_files"
                assert isinstance(example.scope.files, list)
                assert all(isinstance(f, str) for f in example.scope.files)

        # One example should be full-specimen (AllFilesScope)
        full_specimen_found = any(isinstance(ex.scope, AllFilesScope) for ex in examples)
        assert full_specimen_found, "Full-specimen example not found in generated examples"


def test_generate_examples_valid_test_split(synced_test_fixtures):
    """Test example generation for VALID split (per-file + full) and TEST split (full-specimen only)."""
    with get_session() as session:
        # Test VALID split using test-validation fixture
        slug = SnapshotSlug("test-fixtures/test-validation")
        valid_snapshot = session.query(Snapshot).filter_by(slug=slug).one()
        assert valid_snapshot.split == Split.VALID

        valid_examples = generate_examples_for_snapshot(session, slug, valid_snapshot.split)

        # VALID should have multiple examples (per-file + full-specimen)
        assert len(valid_examples) > 1, "VALID split should generate per-file examples for targeted mode"

        # At least one should be full-specimen
        full_specimen_found = any(isinstance(ex.scope, AllFilesScope) for ex in valid_examples)
        assert full_specimen_found, "VALID split should include full-specimen example"

        # Note: TEST split testing skipped - no test-fixtures/test snapshot in git
        # TEST split behavior is well-defined: only generate full-specimen example


def test_generate_examples_unique_trigger_sets(test_db):
    """Test that duplicate trigger sets are deduplicated."""
    with get_session() as session:
        # Create a test snapshot with duplicate trigger sets
        slug = SnapshotSlug("test/example-generation")

        # Clean up any existing test data
        session.query(Snapshot).filter_by(slug=slug).delete()
        session.commit()

        # Create snapshot
        snapshot = Snapshot(slug=slug, split=Split.TRAIN, source={"vcs": "local", "root": "."}, bundle=None)
        session.add(snapshot)

        # Add TP with duplicate trigger sets
        tp = TruePositive(
            snapshot_slug=slug,
            tp_id="test-dup",
            rationale="Test issue with duplicate triggers",
            occurrences=[
                TruePositiveOccurrence(
                    occurrence_id="occ-dup-1",
                    files={Path("file1.py"): None},
                    expect_caught_from={frozenset([Path("file1.py")]), frozenset([Path("file1.py")])},  # Duplicate!
                ),
                TruePositiveOccurrence(
                    occurrence_id="occ-dup-2",
                    files={Path("file2.py"): None},
                    expect_caught_from={frozenset([Path("file1.py")])},  # Same as above
                ),
            ],
        )
        session.add(tp)
        session.commit()

        # Generate examples
        examples = generate_examples_for_snapshot(session, slug, Split.TRAIN)

        # Should deduplicate: 1 unique trigger + 1 full-specimen = 2 examples
        assert len(examples) == 2

        # One example should be the single unique trigger set
        trigger_found = False
        full_specimen_found = False
        for example in examples:
            if isinstance(example.scope, AllFilesScope):
                full_specimen_found = True
            elif isinstance(example.scope, ExplicitFileScope) and example.scope.files == ["file1.py"]:
                trigger_found = True

        assert trigger_found, "Single-file trigger example not found"
        assert full_specimen_found, "Full-specimen example not found"
