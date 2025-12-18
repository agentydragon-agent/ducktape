"""Tests for the listing example module (listing.py).

Tests functions for listing examples, snapshots, and dataset scale.
Consolidated from: test_query_train_examples, test_query_valid_examples,
test_query_full_snapshot_train_examples, test_query_dataset_scale.
"""

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.models.critic_scopes import AllFilesScope
from adgn.props.prompt_optimize.examples.listing import (
    list_full_snapshot_train_examples,
    list_train_examples,
    list_valid_snapshots,
    show_dataset_scale,
)


def test_list_train_examples_with_synced_data(synced_test_fixtures, capsys):
    """Test that list_train_examples produces reasonable output with train examples."""

    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(1)
            .all()
        )
        assert train_examples, "Expected train examples from test-trivial fixture"
        first_example = train_examples[0]
        expected_snapshot = first_example.snapshot_slug

    list_train_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "Training examples" in output
    snapshot_prefix = expected_snapshot.split("/")[0]
    assert snapshot_prefix in output, f"Expected snapshot prefix '{snapshot_prefix}' in output"


def test_list_train_examples_empty_database(test_db, capsys):
    """Test that list_train_examples handles empty database gracefully."""
    list_train_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "Training examples" in output
    assert "first 10 of 0" in output or "(first 10 of 0)" in output


def test_list_valid_snapshots_with_synced_data(synced_test_fixtures, capsys):
    """Test that list_valid_snapshots produces reasonable output with valid snapshots."""
    with get_session() as session:
        valid_snapshots = session.query(Snapshot).filter(Snapshot.split == "valid").all()
        expected_snapshot = valid_snapshots[0].slug
        total_valid_count = len(valid_snapshots)

    list_valid_snapshots()

    captured = capsys.readouterr()
    output = captured.out

    assert "Validation snapshots" in output
    assert f"{total_valid_count} total" in output or f"({total_valid_count} total)" in output
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"


def test_list_valid_snapshots_empty_database(test_db, capsys):
    """Test that list_valid_snapshots handles empty database gracefully."""
    list_valid_snapshots()

    captured = capsys.readouterr()
    output = captured.out

    assert "Validation snapshots" in output
    assert "0 total" in output or "(0 total)" in output


def test_list_full_snapshot_train_examples_with_synced_data(synced_test_fixtures, capsys):
    """Test that list_full_snapshot_train_examples produces reasonable output."""
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )
        assert train_examples, "Expected train examples from test-trivial fixture"

        full_snapshot_examples = [ex for ex in train_examples if isinstance(ex.scope, AllFilesScope)]
        assert full_snapshot_examples, "Expected full-snapshot examples from test-trivial fixture"

        first_example = full_snapshot_examples[0]
        expected_snapshot = first_example.snapshot_slug

    list_full_snapshot_train_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "Full-Snapshot Train Examples" in output
    assert "Snapshot" in output
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    if full_snapshot_examples:
        assert "Usage with run_critic_on_example:" in output
        assert "run_critic_on_example(" in output


def test_list_full_snapshot_train_examples_empty_database(test_db, capsys):
    """Test that list_full_snapshot_train_examples handles empty database gracefully."""
    list_full_snapshot_train_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "Full-Snapshot Train Examples (0 total)" in output


def test_show_dataset_scale_with_synced_data(synced_test_fixtures, capsys):
    """Test that show_dataset_scale produces reasonable output with test fixtures."""
    show_dataset_scale()

    captured = capsys.readouterr()
    output = captured.out

    assert "Dataset sizes by split and scope kind" in output
    assert "train" in output


def test_show_dataset_scale_empty_database(test_db, capsys):
    """Test that show_dataset_scale handles empty database gracefully."""
    show_dataset_scale()

    captured = capsys.readouterr()
    output = captured.out

    assert "Dataset sizes by split and scope kind" in output
