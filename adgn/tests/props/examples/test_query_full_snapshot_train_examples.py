"""Tests for the query_full_snapshot_train_examples example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def test_query_full_snapshot_train_examples_with_synced_data(synced_test_db, capsys):
    """Test that query_full_snapshot_train_examples produces reasonable output with train examples."""
    from adgn.props.examples.query_full_snapshot_train_examples import main

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

        # Find full-snapshot examples (max file count per snapshot)
        max_file_count = max(len(ex.files) for ex in train_examples)
        full_snapshot_examples = [ex for ex in train_examples if len(ex.files) == max_file_count]

        # Remember first full-snapshot example details for verification
        first_example = full_snapshot_examples[0]
        expected_snapshot = first_example.snapshot_slug
        expected_hash_prefix = first_example.files_hash[:8]
        expected_file_count = len(first_example.files)

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_full_snapshot_train_examples.setup_agent_database"):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Full-Snapshot Train Examples" in output
    assert "=" * 80 in output
    assert "Snapshot" in output
    assert "Files Hash" in output
    assert "File Count" in output

    # Verify specific data from fixture appears
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"
    assert expected_hash_prefix in output, f"Expected hash prefix '{expected_hash_prefix}' in output"
    assert str(expected_file_count) in output, f"Expected file count '{expected_file_count}' in output"

    # Verify usage examples section appears if we have data
    if full_snapshot_examples:
        assert "Usage with run_critic_on_example:" in output
        assert "run_critic_on_example(" in output
        assert "snapshot_slug=" in output
        assert "files_hash=" in output


def test_query_full_snapshot_train_examples_empty_database(test_db, capsys):
    """Test that query_full_snapshot_train_examples handles empty database gracefully."""
    from adgn.props.examples.query_full_snapshot_train_examples import main

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_full_snapshot_train_examples.setup_agent_database"):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 examples
    assert "Full-Snapshot Train Examples (0 total)" in output
    assert "Snapshot" in output
    assert "Files Hash" in output
    assert "File Count" in output
