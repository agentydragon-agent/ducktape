"""Tests for the pareto example module (pareto.py).

Tests functions for pareto frontier analysis.
"""

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.models.critic_scopes import AllFilesScope
from adgn.props.prompt_optimize.examples.pareto import (
    show_difficult_examples,
    show_prompts_by_wins_sql,
    show_winning_prompts_orm,
)
from tests.props.conftest import make_critic_and_grader_run, make_grader_output


def test_show_winning_prompts_orm_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that show_winning_prompts_orm produces output with training data."""

    with get_session() as session:
        all_train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )
        train_examples = [ex for ex in all_train_examples if not isinstance(ex.scope, AllFilesScope)][:2]

        if len(train_examples) >= 1:
            make_critic_and_grader_run(
                example=train_examples[0],
                prompt_sha256=test_prompt_sha,
                grader_output=make_grader_output(found_credit=0.8),
                session=session,
            )
            session.commit()

    show_winning_prompts_orm()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top" in output and "examples by best recall" in output


def test_show_winning_prompts_orm_empty(test_db, capsys):
    """Test that show_winning_prompts_orm handles empty database gracefully."""
    show_winning_prompts_orm()

    captured = capsys.readouterr()
    output = captured.out

    assert "examples by best recall" in output


def test_show_prompts_by_wins_sql_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that show_prompts_by_wins_sql produces output with validation data."""
    with get_session() as session:
        all_valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .all()
        )
        valid_examples = [ex for ex in all_valid_examples if not isinstance(ex.scope, AllFilesScope)][:2]

        if len(valid_examples) >= 1:
            make_critic_and_grader_run(
                example=valid_examples[0],
                prompt_sha256=test_prompt_sha,
                grader_output=make_grader_output(found_credit=0.9),
                session=session,
            )
            session.commit()

    show_prompts_by_wins_sql()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top" in output and "prompts by validation examples won" in output


def test_show_prompts_by_wins_sql_empty(test_db, capsys):
    """Test that show_prompts_by_wins_sql handles empty database gracefully."""
    show_prompts_by_wins_sql()

    captured = capsys.readouterr()
    output = captured.out

    assert "prompts by validation examples won" in output


def test_show_difficult_examples_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that show_difficult_examples produces output with training data."""
    with get_session() as session:
        all_train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .all()
        )
        train_examples = [ex for ex in all_train_examples if not isinstance(ex.scope, AllFilesScope)][:2]

        if len(train_examples) >= 1:
            make_critic_and_grader_run(
                example=train_examples[0],
                prompt_sha256=test_prompt_sha,
                grader_output=make_grader_output(found_credit=0.1),  # Low recall = difficult
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
