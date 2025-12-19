"""Tests for the working_with_examples example script."""

from unittest.mock import patch

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.examples.working_with_examples import main


def test_working_with_examples_with_synced_data(synced_test_db, capsys):
    """Test that working_with_examples handles examples correctly."""

    # Get some train examples to query
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(2)
            .all()
        )

        # synced_test_db includes test-trivial (train split) which always has examples
        assert train_examples, "Expected train examples from test-trivial fixture"

        # Remember example details for verification
        example_keys = [(ex.snapshot_slug, ex.scope_hash) for ex in train_examples]

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
    # Check for scope representation (either kind='entire_snapshot' or kind='specific_files' files=[...])
    assert "kind=" in output
    assert "Critic runs:" in output
    assert "Grader runs:" in output


def test_working_with_examples_missing_examples(test_db, capsys):
    """Test that working_with_examples handles missing examples gracefully."""
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
