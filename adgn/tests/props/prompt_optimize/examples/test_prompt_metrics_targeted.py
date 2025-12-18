"""Tests for the prompt_metrics_targeted example module.

Tests functions for targeted mode metrics (uses views directly).
Consolidated from: test_query_train_vs_valid_performance_targeted, test_query_top_prompts.
"""

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.models.critic_scopes import AllFilesScope
from adgn.props.prompt_optimize.examples.prompt_metrics_targeted import (
    show_comprehensive_stats,
    show_top_prompts,
    show_train_vs_valid,
)
from tests.props.conftest import make_critic_and_grader_run, make_grader_output


def test_show_train_vs_valid_with_data(test_train_example_with_runs, test_valid_example_with_runs, capsys):
    """Test that show_train_vs_valid produces combined train/valid output."""
    show_train_vs_valid()

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (targeted mode" in output

    lines = output.strip().split("\n")

    assert any("train" in line.lower() for line in lines), "Expected 'train' split in output"
    assert any("valid" in line.lower() for line in lines), "Expected 'valid' split in output"
    assert any("UCB" in line or "ucb" in line.lower() for line in lines), "Expected UCB column in output"
    assert any("LCB" in line or "lcb" in line.lower() for line in lines), "Expected LCB column in output"


def test_show_train_vs_valid_empty(test_db, capsys):
    """Test that show_train_vs_valid handles empty database gracefully."""
    show_train_vs_valid()

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (targeted mode" in output


def test_show_top_prompts_with_synced_data(synced_test_fixtures, capsys):
    """Test that show_top_prompts produces reasonable output with validation runs."""
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

        prompt_good_sha = hash_and_upsert_prompt("Good prompt for testing")
        prompt_bad_sha = hash_and_upsert_prompt("Bad prompt for testing")

        # Create runs for each example - fetch fresh ORM objects
        for (slug, scope_hash), recall in zip(filtered_keys, [0.9, 0.8], strict=True):
            example = session.get(Example, (slug, scope_hash))
            make_critic_and_grader_run(
                example=example,
                prompt_sha256=prompt_good_sha,
                grader_output=make_grader_output(found_credit=recall),
                session=session,
            )

        # Create bad prompt run for first example
        example_0 = session.get(Example, filtered_keys[0])
        make_critic_and_grader_run(
            example=example_0,
            prompt_sha256=prompt_bad_sha,
            grader_output=make_grader_output(found_credit=0.2),
            session=session,
        )

        session.commit()

    show_top_prompts()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top 10 prompts on validation" in output

    lines = output.strip().split("\n")

    good_prompt_prefix = prompt_good_sha[:6]
    bad_prompt_prefix = prompt_bad_sha[:6]

    assert any(good_prompt_prefix in line and ("85" in line or "0.85" in line) for line in lines), (
        f"Expected good prompt ({good_prompt_prefix}) with recall ~0.85 in output"
    )

    assert any(bad_prompt_prefix in line and ("20" in line or "0.20" in line or "0.2" in line) for line in lines), (
        f"Expected bad prompt ({bad_prompt_prefix}) with recall ~0.20 in output"
    )

    good_indices = [i for i, line in enumerate(lines) if good_prompt_prefix in line]
    bad_indices = [i for i, line in enumerate(lines) if bad_prompt_prefix in line]
    assert all(g < b for g in good_indices for b in bad_indices), (
        f"Expected good prompt (indices {good_indices}) before bad prompt (indices {bad_indices})"
    )


def test_show_top_prompts_empty_database(test_db, capsys):
    """Test that show_top_prompts handles empty database gracefully."""
    show_top_prompts()

    captured = capsys.readouterr()
    output = captured.out

    assert "Top 10 prompts on validation" in output


def test_show_comprehensive_stats_with_data(test_train_example_with_runs, test_valid_example_with_runs, capsys):
    """Test that show_comprehensive_stats produces overview output."""
    show_comprehensive_stats()

    captured = capsys.readouterr()
    output = captured.out

    assert "Prompt Performance Overview" in output


def test_show_comprehensive_stats_empty(test_db, capsys):
    """Test that show_comprehensive_stats handles empty database gracefully."""
    show_comprehensive_stats()

    captured = capsys.readouterr()
    output = captured.out

    # Should print "No prompts found" or similar message
    assert "No prompts found" in output or "Prompt Performance Overview" in output
