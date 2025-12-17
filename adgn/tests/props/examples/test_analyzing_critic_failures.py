"""Tests for the analyzing_critic_failures example script."""

from unittest.mock import patch

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun


def test_analyzing_critic_failures_with_data(synced_test_fixtures, mock_agent_setup, capsys, test_prompt_sha):
    """Test that analyzing_critic_failures displays critic run data correctly."""
    from adgn.props.examples.analyzing_critic_failures import main
    from tests.props.conftest import make_critic_run, make_grader_output, make_grader_run
    from adgn.props.db.snapshots import DBCriticSuccess, DBCriticSubmitPayload
    from adgn.props.db.models import CriticRunStatus
    from adgn.props.ids import SnapshotSlug
    from uuid import uuid4

    # Create test critic run and grader run
    slug = SnapshotSlug("test-fixtures/test-trivial")
    with get_session() as session:
        # Query example from git fixtures
        from adgn.props.db.examples import Example
        example = session.query(Example).filter_by(snapshot_slug=slug).first()
        assert example, "test-trivial fixture not found"

        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            status=CriticRunStatus.COMPLETED,
        )
        session.add(critic_run)
        session.flush()

        # Create grader run for this critique
        grader_run = make_grader_run(
            critic_run=critic_run,
            canonical_issues_snapshot={"true_positives": [], "false_positives": []},
        )
        session.add(grader_run)
        session.commit()

        test_example = (critic_run.snapshot_slug, critic_run.scope_hash)

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
