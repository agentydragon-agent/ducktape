"""Tests for the runs example module (runs.py).

Tests functions for run status, execution traces, and failure analysis.
Consolidated from: test_query_run_status, test_query_execution_traces, test_analyzing_critic_failures.
"""

from datetime import UTC, datetime
import re
from uuid import uuid4

from mcp.types import CallToolResult, TextContent

from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, CriticRunStatus, Event, Snapshot
from adgn.props.ids import SnapshotSlug
from adgn.props.prompt_optimize.examples.runs import analyze_critic_failure, show_execution_traces, show_run_status
from tests.props.conftest import make_critic_run, make_grader_run


def test_show_run_status_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that show_run_status produces reasonable output with run data."""

    with get_session() as session:
        slug = SnapshotSlug("test-fixtures/test-trivial")
        example = session.query(Example).filter_by(snapshot_slug=slug).first()
        assert example, "test-trivial fixture not found"

        success_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            status=CriticRunStatus.COMPLETED,
        )
        session.add(success_run)
        session.commit()

    with get_session() as session:
        critic_runs = session.query(CriticRun).all()
        assert critic_runs, "Expected test critic runs"
        has_completed = any(run.status == CriticRunStatus.COMPLETED for run in critic_runs)

    show_run_status()

    captured = capsys.readouterr()
    output = captured.out

    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output

    if has_completed:
        assert "completed" in output, "Expected 'completed' status in output"

    assert re.search(r"(completed|max_turns_exceeded)\s+\d+", output), "Expected status counts in output"
    assert "Prompts with most max_turns_exceeded" in output


def test_show_run_status_empty_database(test_db, capsys):
    """Test that show_run_status handles empty database gracefully."""
    show_run_status()

    captured = capsys.readouterr()
    output = captured.out

    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output
    assert "Prompts with most max_turns_exceeded" in output


def test_show_execution_traces_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that show_execution_traces produces reasonable output with run data."""
    with get_session() as session:
        snapshot = session.query(Snapshot).first()
        assert snapshot, "Expected snapshots from test fixtures"

        example = session.query(Example).filter_by(snapshot_slug=snapshot.slug).first()
        assert example, "Expected examples from test fixtures"

        transcript_id = uuid4()
        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            transcript_id=transcript_id,
            status=CriticRunStatus.COMPLETED,
        )
        session.add(critic_run)
        session.flush()

        for i in range(3):
            call_event = Event(
                transcript_id=transcript_id,
                sequence_num=i * 2,
                event_type="tool_call",
                timestamp=datetime.now(UTC),
                payload=ToolCall(name=f"test_tool_{i}", args_json=f'{{"arg": {i}}}', call_id=f"call_{i}"),
            )
            session.add(call_event)

            output_event = Event(
                transcript_id=transcript_id,
                sequence_num=i * 2 + 1,
                event_type="tool_call_output",
                timestamp=datetime.now(UTC),
                payload=ToolCallOutput(
                    call_id=f"call_{i}",
                    result=CallToolResult(isError=False, content=[TextContent(type="text", text=f"result {i}")])
                ),
            )
            session.add(output_event)

        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)

        session.commit()

        expected_run_id_prefix = str(critic_run.id)[:6]
        expected_prompt_prefix = test_prompt_sha[:6]
        expected_snapshot = snapshot.slug

    show_execution_traces()

    captured = capsys.readouterr()
    output = captured.out

    assert "Recent critic runs" in output
    assert expected_run_id_prefix in output, f"Expected run ID prefix '{expected_run_id_prefix}' in output"
    assert expected_prompt_prefix in output, f"Expected prompt hash prefix '{expected_prompt_prefix}' in output"
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    assert "Snapshot:" in output
    assert "Prompt:" in output
    assert "Status:" in output
    assert "Tool calls:" in output
    assert "completed" in output
    assert "Tool calls: 3" in output
    assert "Execution trace for run" in output
    assert "tool" in output
    assert "test_tool_0" in output
    assert "result 0" in output


def test_show_execution_traces_empty_database(test_db, capsys):
    """Test that show_execution_traces handles empty database gracefully."""
    show_execution_traces()

    captured = capsys.readouterr()
    output = captured.out

    assert "Recent critic runs" in output


def test_analyze_critic_failure_with_data(synced_test_fixtures, capsys, test_prompt_sha):
    """Test that analyze_critic_failure displays critic run data correctly."""
    slug = SnapshotSlug("test-fixtures/test-trivial")
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=slug).first()
        assert example, "test-trivial fixture not found"

        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            status=CriticRunStatus.COMPLETED,
        )
        session.add(critic_run)
        session.flush()

        grader_run = make_grader_run(
            critic_run=critic_run,
            canonical_issues_snapshot={"true_positives": [], "false_positives": []},
        )
        session.add(grader_run)
        session.commit()

        test_scope_hash = critic_run.scope_hash

    # Call with actual values
    analyze_critic_failure(str(slug), test_scope_hash)

    captured = capsys.readouterr()
    output = captured.out

    assert "Found" in output and "critic runs for example" in output
    assert "Snapshot:" in output


def test_analyze_critic_failure_no_data(test_db, capsys):
    """Test that analyze_critic_failure handles missing critic runs gracefully."""
    # Use a fake example that doesn't exist
    analyze_critic_failure("nonexistent/2025-01-01-00", "0" * 64)

    captured = capsys.readouterr()
    output = captured.out

    assert "No critic runs found" in output
