"""Tests for the query_full_snapshot_train_examples example script."""

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def test_query_full_snapshot_train_examples_with_synced_data(synced_test_db, mock_agent_setup, capsys):
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

        if not train_examples:
            pytest.skip("No train examples in synced_test_db")

        # Find full-snapshot examples using is_whole_snapshot flag
        full_snapshot_examples = [ex for ex in train_examples if ex.is_whole_snapshot]

        if not full_snapshot_examples:
            pytest.skip("No whole-snapshot examples in synced_test_db")

        # Remember first full-snapshot example details for verification
        first_example = full_snapshot_examples[0]
        expected_snapshot = first_example.snapshot_slug
        # Whole-snapshot examples have files=NULL and files_hash=NULL, so we check snapshot slug only

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Full-Snapshot Train Examples" in output
    assert "=" * 80 in output
    assert "Snapshot" in output

    # Verify specific data from fixture appears
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    # Verify usage examples section appears if we have data
    if full_snapshot_examples:
        assert "Usage with run_critic_on_example:" in output
        assert "run_critic_on_example(" in output
        assert "snapshot_slug=" in output
        # Whole-snapshot examples use files_hash=None
        assert "files_hash=None" in output


def test_query_full_snapshot_train_examples_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_full_snapshot_train_examples handles empty database gracefully."""
    from adgn.props.examples.query_full_snapshot_train_examples import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 examples
    assert "Full-Snapshot Train Examples (0 total)" in output
    assert "Snapshot" in output
    assert "Files Hash" in output
    assert "File Count" in output
