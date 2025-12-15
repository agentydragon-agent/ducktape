"""Tests for automatic example generation from expect_caught_from data."""

from __future__ import annotations

from pathlib import Path

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot, TruePositive
from adgn.props.db.sync._sync import generate_examples_for_snapshot
from adgn.props.files_hash import hash_file_set
from adgn.props.ids import SnapshotSlug
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.splits import Split


def test_generate_examples_train_split(synced_test_db):
    """Test example generation for TRAIN split creates per-trigger examples + full-specimen."""
    with get_session() as session:
        # Pick a known TRAIN snapshot with multiple trigger sets
        slug = SnapshotSlug("ducktape/2025-12-04-00")
        snapshot = session.query(Snapshot).filter_by(slug=slug).one()
        assert snapshot.split == Split.TRAIN

        # Generate examples
        examples = generate_examples_for_snapshot(session, slug, snapshot.split)

        # Should have multiple examples (one per unique trigger set + full-specimen)
        assert len(examples) > 1

        # Each example should be an Example ORM object
        for example in examples:
            assert isinstance(example, Example)

            if example.is_whole_snapshot:
                # Whole-snapshot examples have NULL files/hash
                assert example.files is None
                assert example.files_hash is None
            else:
                # File-set examples have non-NULL files/hash
                assert isinstance(example.files, list)
                assert all(isinstance(f, str) for f in example.files)
                assert isinstance(example.files_hash, str)
                assert len(example.files_hash) == 64  # SHA256 hex length

                # Verify hash matches file set
                file_set = {Path(f) for f in example.files}
                expected_hash = hash_file_set(file_set)
                assert example.files_hash == expected_hash

        # One example should be full-specimen (all files with issues)
        all_files: set[Path] = set()
        for tp in snapshot.true_positives:
            for tp_occ in tp.occurrences:
                all_files.update(tp_occ.files.keys())
        for fp in snapshot.false_positives:
            for fp_occ in fp.occurrences:
                all_files.update(fp_occ.files.keys())

        # Find full-specimen example (should be marked as is_whole_snapshot=TRUE)
        full_specimen_found = any(example.is_whole_snapshot for example in examples)
        assert full_specimen_found, "Full-specimen example not found in generated examples"


def test_generate_examples_valid_test_split(synced_test_db):
    """Test example generation for VALID split (per-file + full) and TEST split (full-specimen only)."""
    with get_session() as session:
        # Test VALID split (should generate per-file + full-specimen like TRAIN)
        valid_snapshot = session.query(Snapshot).filter_by(split=Split.VALID).first()
        if valid_snapshot:
            valid_examples = generate_examples_for_snapshot(session, valid_snapshot.slug, valid_snapshot.split)

            # VALID should have multiple examples (per-file + full-specimen)
            assert len(valid_examples) > 1, "VALID split should generate per-file examples for targeted mode"

            # At least one should be full-specimen
            full_specimen_found = any(ex.is_whole_snapshot for ex in valid_examples)
            assert full_specimen_found, "VALID split should include full-specimen example"

        # Test TEST split (should generate only full-specimen)
        test_snapshot = session.query(Snapshot).filter_by(split=Split.TEST).first()
        if test_snapshot:
            test_examples = generate_examples_for_snapshot(session, test_snapshot.slug, test_snapshot.split)

            # TEST should have exactly ONE example (full-specimen only)
            assert len(test_examples) == 1, "TEST split should only generate full-specimen example"
            assert test_examples[0].is_whole_snapshot is True
            assert test_examples[0].files is None
            assert test_examples[0].files_hash is None

        if not valid_snapshot and not test_snapshot:
            pytest.skip("No VALID or TEST snapshots in test database")


def test_generate_examples_unique_trigger_sets(synced_test_db):
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
            if example.is_whole_snapshot:
                full_specimen_found = True
            elif example.files == ["file1.py"]:
                trigger_found = True

        assert trigger_found, "Single-file trigger example not found"
        assert full_specimen_found, "Full-specimen example not found"

        # Cleanup (delete children first due to FK constraints)
        session.query(TruePositive).filter_by(snapshot_slug=slug).delete()
        session.query(Snapshot).filter_by(slug=slug).delete()
        session.commit()
