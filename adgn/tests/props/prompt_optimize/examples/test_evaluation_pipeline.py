"""Tests for the evaluation_pipeline example module.

Tests async helper functions for running critic+grader evaluations.
Note: This module tests the helper functions, not the full async pipeline
which requires MCP infrastructure.
"""

import asyncio
import inspect

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.prompt_optimize.examples import evaluation_pipeline
from adgn.props.prompt_optimize.examples.evaluation_pipeline import evaluate_example, main


def test_module_imports(synced_test_fixtures):
    """Test that evaluation_pipeline module imports without errors."""

    # Verify the module has expected components
    assert hasattr(evaluation_pipeline, "evaluate_example")
    assert hasattr(evaluation_pipeline, "main")


def test_evaluate_example_signature(synced_test_fixtures):
    """Test that evaluate_example has expected signature."""
    # Should be an async function
    assert asyncio.iscoroutinefunction(evaluate_example)

    # Check signature
    sig = inspect.signature(evaluate_example)
    params = list(sig.parameters.keys())

    assert "example" in params
    assert "prompt_sha256" in params


def test_main_is_async(synced_test_fixtures):
    """Test that main is an async function."""
    assert asyncio.iscoroutinefunction(main)


def test_example_data_accessible(synced_test_fixtures):
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
            assert example.scope_hash
            assert example.scope is not None
