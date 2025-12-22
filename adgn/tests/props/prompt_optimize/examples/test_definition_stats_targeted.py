"""Tests for the definition_stats_targeted example module.

Tests functions for targeted mode definition statistics (uses views directly).
Consolidated from: test_query_train_vs_valid_performance_targeted, test_query_top_definitions.
"""

import pytest
from rich.console import Console

from adgn.props.agent_defs.prompt_optimizer.examples.definition_stats_targeted import (
    show_comprehensive_stats,
    show_top_definitions,
    show_train_vs_valid,
)
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.models.critic_scopes import AllFilesScope
from tests.props.conftest import make_critic_and_grader_run, make_grader_output


@pytest.fixture
def wide_console() -> Console:
    """Console with fixed width for consistent table output in tests."""
    return Console(width=120)


def test_show_train_vs_valid_with_data(test_train_example_with_runs, test_valid_example_with_runs, capsys, wide_console):
    """Test that show_train_vs_valid produces combined train/valid output."""
    show_train_vs_valid(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (targeted mode" in output

    lines = output.strip().split("\n")

    assert any("train" in line.lower() for line in lines), "Expected 'train' split in output"
    assert any("valid" in line.lower() for line in lines), "Expected 'valid' split in output"
    # UCB/LCB columns should appear with width=120 console
    assert any("UCB" in line for line in lines), "Expected UCB column in output"
    assert any("LCB" in line for line in lines), "Expected LCB column in output"


def test_show_train_vs_valid_empty(test_db, capsys, wide_console):
    """Test that show_train_vs_valid handles empty database gracefully."""
    show_train_vs_valid(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (targeted mode" in output


def test_show_top_definitions_with_synced_data(synced_test_db, capsys, wide_console):
    """Test that show_top_definitions produces reasonable output with validation runs.

    NOTE: This test writes to the database (creates critic/grader runs) so it must
    use synced_test_db, not synced_test_db.
    """
    with get_session() as session:
        # Query valid examples - use subquery to avoid detached instance issues
        # First get the keys we need
        valid_example_rows = (
            session.query(Example.snapshot_slug, Example.scope_hash, Example.scope)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .all()
        )
        # Filter for non-AllFilesScope and take first 2
        filtered_keys = [
            (row.snapshot_slug, row.scope_hash)
            for row in valid_example_rows
            if not isinstance(row.scope, AllFilesScope)
        ][:2]

        assert len(filtered_keys) >= 2, "Expected at least 2 valid ExplicitFileScope examples"

        # Create runs for each example - fetch fresh ORM objects
        for (slug, scope_hash), recall in zip(filtered_keys, [0.9, 0.8], strict=True):
            example = session.get(Example, (slug, scope_hash))
            make_critic_and_grader_run(
                example=example,
                grader_output=make_grader_output(found_credit=recall),
                session=session,
            )

        # Create bad prompt run for first example
        example_0 = session.get(Example, filtered_keys[0])
        make_critic_and_grader_run(
            example=example_0,
            grader_output=make_grader_output(found_credit=0.2),
            session=session,
        )

        session.commit()

    show_top_definitions(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    # The function now shows definitions, not prompts (grouped by agent_definition_id)
    assert "Top 10 definitions on validation" in output


def test_show_top_definitions_empty_database(test_db, capsys, wide_console):
    """Test that show_top_definitions handles empty database gracefully."""
    show_top_definitions(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    assert "Top 10 definitions on validation" in output


def test_show_comprehensive_stats_with_data(test_train_example_with_runs, test_valid_example_with_runs, capsys, wide_console):
    """Test that show_comprehensive_stats produces overview output."""
    show_comprehensive_stats(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    assert "Definition Performance Overview" in output


def test_show_comprehensive_stats_empty(test_db, capsys, wide_console):
    """Test that show_comprehensive_stats handles empty database gracefully."""
    show_comprehensive_stats(wide_console)

    captured = capsys.readouterr()
    output = captured.out

    # Always shows header (base definitions exist from sync)
    assert "Definition Performance Overview" in output
