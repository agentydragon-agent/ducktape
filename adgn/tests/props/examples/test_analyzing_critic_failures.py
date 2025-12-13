"""Tests for the analyzing_critic_failures example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GraderRun


def test_analyzing_critic_failures_with_data(synced_test_db, mock_agent_setup, capsys):
    """Test that analyzing_critic_failures displays critic run data correctly."""
    from adgn.props.examples.analyzing_critic_failures import main

    # Find a critic run with grader result to use as test example
    with get_session() as session:
        result = (
            session.query(CriticRun, GraderRun)
            .join(GraderRun, CriticRun.critique_id == GraderRun.critique_id)
            .first()
        )
        if not result:
            pytest.skip("No critic runs with grader results in synced_test_db")

        critic_run, _grader_run = result
        test_example = (critic_run.snapshot_slug, critic_run.files_hash)

    # Mock the example to analyze
    with patch("adgn.props.examples.analyzing_critic_failures.example_to_analyze", test_example):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Found" in output and "critic runs for example" in output
    assert "Snapshot:" in output
    assert "Run Status" in output
    assert "Grader Results" in output or "Run Status" in output


def test_analyzing_critic_failures_no_data(test_db, mock_agent_setup, capsys):
    """Test that analyzing_critic_failures handles missing critic runs gracefully."""
    from adgn.props.examples.analyzing_critic_failures import main

    # Use a fake example that doesn't exist
    fake_example = ("nonexistent/2025-01-01-00", "0" * 64)

    # Mock the example to analyze
    with patch("adgn.props.examples.analyzing_critic_failures.example_to_analyze", fake_example):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show "no data" message
    assert "No critic runs found" in output
