"""Tests for the query_valid_examples example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def test_query_valid_examples_with_synced_data(synced_test_db, capsys):
    """Test that query_valid_examples produces reasonable output with valid examples."""
    from adgn.props.examples.query_valid_examples import main

    # Verify we have valid examples and capture their details
    with get_session() as session:
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .limit(1)
            .all()
        )

        if not valid_examples:
            pytest.skip("No valid examples in synced_test_db")

        # Remember first example details for verification
        first_example = valid_examples[0]
        expected_snapshot = first_example.snapshot_slug
        expected_hash_prefix = first_example.files_hash[:16]
        total_valid_count = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .count()
        )

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_valid_examples.setup_agent_database"):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Validation examples" in output
    assert f"{total_valid_count} total" in output or f"({total_valid_count} total)" in output

    # Verify specific data from fixture appears
    assert "/" in output  # Should have snapshot_slug / files_hash format
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"
    assert expected_hash_prefix in output, f"Expected hash prefix '{expected_hash_prefix}' in output"

    # Verify file information appears
    assert "files" in output.lower() or "Files:" in output


def test_query_valid_examples_empty_database(test_db, capsys):
    """Test that query_valid_examples handles empty database gracefully."""
    from adgn.props.examples.query_valid_examples import main

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_valid_examples.setup_agent_database"):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 examples
    assert "Validation examples" in output
    assert "0 total" in output or "(0 total)" in output
