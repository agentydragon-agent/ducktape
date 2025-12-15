"""Tests for the query_run_status example script."""

import re

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun


def test_query_run_status_with_data(synced_test_db, mock_agent_setup, capsys):
    """Test that query_run_status produces reasonable output with run data."""
    from adgn.props.examples.query_run_status import main  # noqa: PLC0415

    # Verify we have critic runs and check status distribution
    with get_session() as session:
        critic_runs = session.query(CriticRun).filter(CriticRun.output.isnot(None)).all()

        if not critic_runs:
            pytest.skip("No critic runs with output in synced_test_db")

        # Check if we have any success or max_turns_exceeded runs
        has_success = any(run.output.get("tag") == "success" for run in critic_runs)
        has_max_turns = any(run.output.get("tag") == "max_turns_exceeded" for run in critic_runs)

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output

    # Verify actual status counts appear (not just headers)
    if has_success:
        assert "success:" in output, "Expected 'success:' status count in output"
    if has_max_turns:
        assert "max_turns_exceeded:" in output, "Expected 'max_turns_exceeded:' status count in output"

    # Verify numeric counts appear (at least one digit for status counts)
    # Should have status counts like "success: 5" or "max_turns_exceeded: 2"
    assert re.search(r"(success|max_turns_exceeded):\s+\d+", output), "Expected status counts with numbers in output"

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
