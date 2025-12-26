"""Tests for the definition_stats_targeted example module.

Tests functions for targeted mode definition statistics (uses views directly).
Consolidated from: test_query_train_vs_valid_performance_targeted, test_query_top_definitions.
"""

import pytest
from rich.console import Console

from props.examples.definition_stats_targeted import (
    show_comprehensive_stats,
    show_top_definitions,
    show_train_vs_valid,
)
from props.db.session import get_session
from props.db.examples import Example
from props.db.models import Snapshot
from props.models.examples import ExampleKind, WholeSnapshotExample
from tests.conftest import get_tp_occurrences_for_snapshot, make_critic_and_grader_run, make_grader_output


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
        # Query valid whole_snapshot examples - test fixtures only have whole_snapshot for valid
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .filter(Example.example_kind == ExampleKind.WHOLE_SNAPSHOT)
            .limit(2)
            .all()
        )

        assert len(valid_examples) >= 2, "Expected at least 2 valid whole_snapshot examples"

        # Create runs for each example
        for example, recall in zip(valid_examples, [0.9, 0.8], strict=True):
            tp_occs = get_tp_occurrences_for_snapshot(example.snapshot_slug, session)
            make_critic_and_grader_run(
                example=example,
                grader_output=make_grader_output(tp_occurrences=tp_occs, found_credit=recall),
                session=session,
            )

        # Create bad prompt run for first example
        tp_occs = get_tp_occurrences_for_snapshot(valid_examples[0].snapshot_slug, session)
        make_critic_and_grader_run(
            example=valid_examples[0],
            grader_output=make_grader_output(tp_occurrences=tp_occs, found_credit=0.2),
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
