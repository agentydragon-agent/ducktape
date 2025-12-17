"""Tests for the query_run_status example script."""

import re

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun


def test_query_run_status_with_data(synced_test_fixtures, mock_agent_setup, capsys, test_prompt_sha):
    """Test that query_run_status produces reasonable output with run data."""
    from adgn.props.examples.query_run_status import main  # noqa: PLC0415
    from tests.props.conftest import make_critic_run
    from adgn.props.db.snapshots import DBCriticSuccess, DBCriticSubmitPayload
    from adgn.props.db.models import CriticRunStatus
    from adgn.props.ids import SnapshotSlug

    # Create test critic runs
    with get_session() as session:
        # Query example from git fixtures
        from adgn.props.db.examples import Example
        slug = SnapshotSlug("test-fixtures/test-trivial")
        example = session.query(Example).filter_by(snapshot_slug=slug).first()
        assert example, "test-trivial fixture not found"

        # Create a successful run
        success_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            status=CriticRunStatus.COMPLETED,
        )
        session.add(success_run)
        session.commit()

    # Verify we have critic runs and check status distribution
    with get_session() as session:
        critic_runs = session.query(CriticRun).all()
        assert critic_runs, "Expected test critic runs"

        # Check if we have any success or max_turns_exceeded runs
        has_success = any(run.status == CriticRunStatus.COMPLETED for run in critic_runs)
        has_max_turns = any(run.status == CriticRunStatus.MAX_TURNS_EXCEEDED for run in critic_runs)

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output

    # Verify actual status counts appear (not just headers)
    # Table format is "  success              1" (space-separated, not colon-separated)
    if has_success:
        assert "success" in output, "Expected 'success' status in output"
    if has_max_turns:
        assert "max_turns_exceeded" in output, "Expected 'max_turns_exceeded' status in output"

    # Verify numeric counts appear (at least one digit for status counts)
    # Status counts are in table format: "  success              1"
    assert re.search(r"(success|max_turns_exceeded)\s+\d+", output), "Expected status counts with numbers in output"

    # Verify prompts section appears
    assert "Prompts with most max_turns_exceeded" in output


def test_query_run_status_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_run_status handles empty database gracefully."""
    from adgn.props.examples.query_run_status import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show headers even with no data
    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output
    assert "Prompts with most max_turns_exceeded" in output
