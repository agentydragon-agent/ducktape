"""Tests for automatic example generation from expect_caught_from data."""

from __future__ import annotations

from pathlib import Path

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot, TruePositive
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

        # Each example should have (files_list, files_hash)
        for files_list, files_hash in examples:
            assert isinstance(files_list, list)
            assert all(isinstance(f, str) for f in files_list)
            assert isinstance(files_hash, str)
            assert len(files_hash) == 64  # SHA256 hex length

            # Verify hash matches file set
            file_set = {Path(f) for f in files_list}
            expected_hash = hash_file_set(file_set)
            assert files_hash == expected_hash

        # One example should be full-specimen (all files with issues)
        all_files: set[Path] = set()
        for tp in snapshot.true_positives:
            for tp_occ in tp.occurrences:
                all_files.update(tp_occ.files.keys())
        for fp in snapshot.false_positives:
            for fp_occ in fp.occurrences:
                all_files.update(fp_occ.files.keys())

        all_files_str = {str(f) for f in all_files}

        # Find full-specimen example (may not be last due to hash-based ordering)
        full_specimen_found = False
        for files_list, _ in examples:
            if set(files_list) == all_files_str:
                full_specimen_found = True
                break

        assert full_specimen_found, "Full-specimen example not found in generated examples"


def test_generate_examples_valid_test_split(synced_test_db):
    """Test example generation for VALID/TEST splits creates only full-specimen example."""
    with get_session() as session:
        # Find a VALID or TEST snapshot
        snapshot = session.query(Snapshot).filter(Snapshot.split.in_([Split.VALID, Split.TEST])).first()

        if not snapshot:
            pytest.skip("No VALID/TEST snapshots in test database")

        # Generate examples
        examples = generate_examples_for_snapshot(session, snapshot.slug, snapshot.split)

        # Should have exactly ONE example (full-specimen only)
        assert len(examples) == 1

        files_list, files_hash = examples[0]

        # Should contain all files with issues
        all_files: set[Path] = set()
        for tp in snapshot.true_positives:
            for tp_occ in tp.occurrences:
                all_files.update(tp_occ.files.keys())
        for fp in snapshot.false_positives:
            for fp_occ in fp.occurrences:
                all_files.update(fp_occ.files.keys())

        assert set(files_list) == {str(f) for f in all_files}


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
                    files={Path("file1.py"): None},
                    expect_caught_from={frozenset([Path("file1.py")]), frozenset([Path("file1.py")])},  # Duplicate!
                ),
                TruePositiveOccurrence(
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
        for files_list, _ in examples:
            if files_list == ["file1.py"]:
                trigger_found = True
            elif set(files_list) == {"file1.py", "file2.py"}:
                full_specimen_found = True

        assert trigger_found, "Single-file trigger example not found"
        assert full_specimen_found, "Full-specimen example not found"

        # Cleanup (delete children first due to FK constraints)
        session.query(TruePositive).filter_by(snapshot_slug=slug).delete()
        session.query(Snapshot).filter_by(slug=slug).delete()
        session.commit()
