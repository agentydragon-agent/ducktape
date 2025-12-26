"""Tests for the working_with_examples example script."""

from unittest.mock import patch

from sqlalchemy.orm import Session

from props.db.config import DatabaseConfig
from props.db.examples import Example
from props.db.models import Snapshot
from props.examples.working_with_examples import main
from props.models.examples import ExampleKind


def test_working_with_examples_with_synced_data(synced_test_session: Session, capsys):
    """Test that working_with_examples handles examples correctly."""
    # Get some train examples to query
    train_examples = (
        synced_test_session.query(Example)
        .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
        .filter(Snapshot.split == "train")
        .limit(2)
        .all()
    )

    # synced_test_db includes test-trivial (train split) which always has examples
    assert train_examples, "Expected train examples from test-trivial fixture"

    # Remember example details for verification - new format: (snapshot_slug, example_kind, files_hash)
    example_keys = [(ex.snapshot_slug, ex.example_kind, ex.files_hash) for ex in train_examples]

    # Mock the hardcoded example keys in the script to use our test data
    with patch("props.examples.working_with_examples.examples", example_keys):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Querying example details" in output

    # Should show found examples (not "not found")
    assert "✓ " in output
    # Check for example kind in output
    assert "whole_snapshot" in output or "file_set" in output
    assert "Critic runs:" in output
    assert "Grader runs:" in output


def test_working_with_examples_missing_examples(test_db: DatabaseConfig, capsys):
    """Test that working_with_examples handles missing examples gracefully."""
    # Use fake example keys that don't exist - new format: (snapshot_slug, example_kind, files_hash)
    fake_examples = [
        ("nonexistent/2025-01-01-00", ExampleKind.WHOLE_SNAPSHOT, None),
    ]

    # Mock the hardcoded example keys
    with patch("props.examples.working_with_examples.examples", fake_examples):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header
    assert "Querying example details" in output

    # Should handle missing examples gracefully
    assert "❌ Example not found" in output
