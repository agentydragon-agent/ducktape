"""Tests for the pareto example module (pareto.py).

Tests functions for pareto frontier analysis.
"""

from adgn.props.agent_defs.prompt_optimizer.examples.pareto import (
    show_definitions_by_wins_sql,
    show_difficult_examples,
    show_winning_definitions_orm,
)
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.models.examples import ExampleKind, WholeSnapshotExample
from tests.props.conftest import get_tp_occurrences_for_snapshot, make_critic_and_grader_run, make_grader_output


def test_show_winning_definitions_orm_with_data(synced_test_db, capsys):
    """Test that show_winning_definitions_orm produces output with training data."""

    with get_session() as session:
        all_train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )
        train_examples = [ex for ex in all_train_examples if ex.example_kind != ExampleKind.WHOLE_SNAPSHOT][:2]

        if len(train_examples) >= 1:
            tp_occs = get_tp_occurrences_for_snapshot(train_examples[0].snapshot_slug, session)
            make_critic_and_grader_run(
                example=train_examples[0],
                grader_output=make_grader_output(tp_occurrences=tp_occs, found_credit=0.8),
                session=session,
            )
            session.commit()

    show_winning_definitions_orm()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top" in output and "examples by best mean credit" in output


def test_show_winning_definitions_orm_empty(test_db, capsys):
    """Test that show_winning_definitions_orm handles empty database gracefully."""
    show_winning_definitions_orm()

    captured = capsys.readouterr()
    output = captured.out

    assert "examples by best mean credit" in output


def test_show_definitions_by_wins_sql_with_data(synced_test_db, capsys):
    """Test that show_definitions_by_wins_sql produces output with validation data."""
    with get_session() as session:
        # Use whole_snapshot examples - no file validation issues
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .filter(Example.example_kind == ExampleKind.WHOLE_SNAPSHOT)
            .limit(2)
            .all()
        )

        if len(valid_examples) >= 1:
            tp_occs = get_tp_occurrences_for_snapshot(valid_examples[0].snapshot_slug, session)
            make_critic_and_grader_run(
                example=valid_examples[0],
                grader_output=make_grader_output(tp_occurrences=tp_occs, found_credit=0.9),
                session=session,
            )
            session.commit()

    show_definitions_by_wins_sql()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top" in output and "critic definitions by validation examples won" in output


def test_show_definitions_by_wins_sql_empty(test_db, capsys):
    """Test that show_definitions_by_wins_sql handles empty database gracefully."""
    show_definitions_by_wins_sql()

    captured = capsys.readouterr()
    output = captured.out

    assert "critic definitions by validation examples won" in output


def test_show_difficult_examples_with_data(synced_test_db, capsys):
    """Test that show_difficult_examples produces output with training data."""
    with get_session() as session:
        all_train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )
        train_examples = [ex for ex in all_train_examples if ex.example_kind != ExampleKind.WHOLE_SNAPSHOT][:2]

        if len(train_examples) >= 1:
            tp_occs = get_tp_occurrences_for_snapshot(train_examples[0].snapshot_slug, session)
            make_critic_and_grader_run(
                example=train_examples[0],
                grader_output=make_grader_output(tp_occurrences=tp_occs, found_credit=0.1),  # Low recall = difficult
                session=session,
            )
            session.commit()

    show_difficult_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "most difficult" in output and "examples" in output


def test_show_difficult_examples_empty(test_db, capsys):
    """Test that show_difficult_examples handles empty database gracefully."""
    show_difficult_examples()

    captured = capsys.readouterr()
    output = captured.out

    assert "difficult" in output and "examples" in output
