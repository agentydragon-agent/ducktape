"""Tests for the query_train_examples example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def test_query_train_examples_with_synced_data(synced_test_db, capsys):
    """Test that query_train_examples produces reasonable output with train examples."""
    from adgn.props.examples.query_train_examples import main

    # Verify we have train examples and capture their details
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(1)
            .all()
        )

        if not train_examples:
            pytest.skip("No train examples in synced_test_db")

        # Remember first example details for verification
        first_example = train_examples[0]
        expected_snapshot = first_example.snapshot_slug
        expected_hash_prefix = first_example.files_hash[:16]

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_train_examples.setup_agent_database"):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Training examples" in output
    assert "first 10 of" in output or "first" in output

    # Verify specific data from fixture appears
    assert "/" in output  # Should have snapshot_slug / files_hash format
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"
    assert expected_hash_prefix in output, f"Expected hash prefix '{expected_hash_prefix}' in output"

    # Verify file information appears
    assert "files" in output.lower() or "Files:" in output


def test_query_train_examples_empty_database(test_db, capsys):
    """Test that query_train_examples handles empty database gracefully."""
    from adgn.props.examples.query_train_examples import main

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_train_examples.setup_agent_database"):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 examples
    assert "Training examples" in output
    assert "first 10 of 0" in output or "(first 10 of 0)" in output
