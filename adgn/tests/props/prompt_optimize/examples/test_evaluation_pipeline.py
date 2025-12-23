"""Tests for the evaluation_pipeline example module.

Tests that training examples can be accessed for the evaluation pipeline.
"""

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot


def test_example_data_accessible(synced_test_db):
    """Test that training examples can be accessed for evaluation pipeline."""
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(5)
            .all()
        )

        # Verify we have examples to evaluate
        assert train_examples, "Expected train examples for evaluation pipeline"

        # Verify examples have required attributes
        for example in train_examples:
            assert example.snapshot_slug
            assert example.example_kind  # whole_snapshot or file_set
            # files_hash may be None for whole_snapshot examples
            # scope is a computed property from example_kind + files
            assert example.example_kind in ("whole_snapshot", "file_set")
