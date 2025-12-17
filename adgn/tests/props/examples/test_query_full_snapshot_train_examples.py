"""Tests for the query_full_snapshot_train_examples example script."""

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.examples import Example

def test_query_full_snapshot_train_examples_with_synced_data(synced_test_fixtures, mock_agent_setup, capsys):
    """Test that query_full_snapshot_train_examples produces reasonable output with train examples."""
    from adgn.props.examples.query_full_snapshot_train_examples import main  # noqa: PLC0415

    # Verify we have train examples and find the max file count
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )

        # synced_test_fixtures includes test-trivial (train split) which always has examples
        assert train_examples, "Expected train examples from test-trivial fixture"

        # Find full-snapshot examples using AllFilesScope type check
        from adgn.props.models.critic_scopes import AllFilesScope
        full_snapshot_examples = [ex for ex in train_examples if isinstance(ex.scope, AllFilesScope)]

        # sync_all() generates full-snapshot examples for all snapshots
        assert full_snapshot_examples, "Expected full-snapshot examples from test-trivial fixture"

        # Remember first full-snapshot example details for verification
        first_example = full_snapshot_examples[0]
        expected_snapshot = first_example.snapshot_slug
        # Whole-snapshot examples use AllFilesScope, so we check snapshot slug and scope_hash

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure (table uses Rich formatting, not plain text separators)
    assert "Full-Snapshot Train Examples" in output
    assert "Snapshot" in output

    # Verify specific data from fixture appears
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    # Verify usage examples section appears if we have data
    if full_snapshot_examples:
        assert "Usage with run_critic_on_example:" in output
        assert "run_critic_on_example(" in output
        assert "snapshot_slug=" in output
        # Whole-snapshot examples use scope_hash for AllFilesScope
        assert "scope_hash=" in output

def test_query_full_snapshot_train_examples_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_full_snapshot_train_examples handles empty database gracefully."""
    from adgn.props.examples.query_full_snapshot_train_examples import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 examples
    assert "Full-Snapshot Train Examples (0 total)" in output
    assert "Snapshot" in output
    assert "Scope Hash" in output or "scope_hash" in output
