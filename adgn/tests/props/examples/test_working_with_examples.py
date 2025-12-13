"""Tests for the working_with_examples example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Example, Snapshot


def test_working_with_examples_with_synced_data(synced_test_db, mock_agent_setup, capsys):
    """Test that working_with_examples handles examples correctly."""
    from adgn.props.examples.working_with_examples import main

    # Get some train examples to query
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(2)
            .all()
        )

        if not train_examples:
            pytest.skip("No train examples in synced_test_db")

        # Remember example details for verification
        example_keys = [(ex.snapshot_slug, ex.files_hash) for ex in train_examples]

    # Mock the hardcoded example keys in the script to use our test data
    with patch("adgn.props.examples.working_with_examples.examples", example_keys):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Querying example details" in output

    # Should show found examples (not "not found")
    assert "✓ " in output
    assert "Files (" in output
    assert "Critic runs:" in output
    assert "Grader runs:" in output


def test_working_with_examples_missing_examples(test_db, mock_agent_setup, capsys):
    """Test that working_with_examples handles missing examples gracefully."""
    from adgn.props.examples.working_with_examples import main

    # Use fake example keys that don't exist
    fake_examples = [
        ("nonexistent/2025-01-01-00", "0" * 64),
    ]

    # Mock the hardcoded example keys
    with patch("adgn.props.examples.working_with_examples.examples", fake_examples):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header
    assert "Querying example details" in output

    # Should handle missing examples gracefully
    assert "❌ Example not found" in output
