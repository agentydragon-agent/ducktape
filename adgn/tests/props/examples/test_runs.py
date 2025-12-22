"""Tests for the runs example module (runs.py).

Tests functions for run status, execution traces, and failure analysis.
Consolidated from: test_query_run_status, test_query_execution_traces, test_analyzing_critic_failures.
"""

from datetime import UTC, datetime

import re

from mcp.types import CallToolResult, TextContent
from sqlalchemy.orm import Session

from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.props.agent_types import AgentType, CriticTypeConfig
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun, AgentRunStatus, Event, Snapshot
from adgn.props.examples.runs import analyze_critic_failure, show_execution_traces, show_run_status
from adgn.props.ids import SnapshotSlug
from tests.props.conftest import make_critic_run, make_grader_run


def test_show_run_status_with_data(synced_test_session: Session, capsys):
    """Test that show_run_status produces reasonable output with run data."""
    slug = SnapshotSlug("test-fixtures/test-trivial")
    example = synced_test_session.query(Example).filter_by(snapshot_slug=slug).first()
    assert example, "test-trivial fixture not found"

    success_run = make_critic_run(
        example=example,
        status=AgentRunStatus.COMPLETED,
    )
    synced_test_session.add(success_run)
    synced_test_session.commit()

    # Query AgentRun with critic agent_type
    synced_test_session.expire_all()
    critic_runs = synced_test_session.query(AgentRun).filter(
        AgentRun.type_config["agent_type"].astext == AgentType.CRITIC
    ).all()
    assert critic_runs, "Expected test critic runs"
    has_completed = any(run.status == AgentRunStatus.COMPLETED for run in critic_runs)

    show_run_status()

    captured = capsys.readouterr()
    output = captured.out

    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output

    if has_completed:
        assert "completed" in output, "Expected 'completed' status in output"

    assert re.search(r"(completed|max_turns_exceeded)\s+\d+", output), "Expected status counts in output"
    assert "Definitions with most max_turns_exceeded" in output


def test_show_run_status_empty_database(test_db: DatabaseConfig, capsys):
    """Test that show_run_status handles empty database gracefully."""
    show_run_status()

    captured = capsys.readouterr()
    output = captured.out

    assert "Critic Run Status:" in output
    assert "Grader Run Status:" in output
    assert "Definitions with most max_turns_exceeded" in output


def test_show_execution_traces_with_data(synced_test_session: Session, capsys):
    """Test that show_execution_traces produces reasonable output with run data."""
    snapshot = synced_test_session.query(Snapshot).first()
    assert snapshot, "Expected snapshots from test fixtures"

    example = synced_test_session.query(Example).filter_by(snapshot_slug=snapshot.slug).first()
    assert example, "Expected examples from test fixtures"

    critic_run = make_critic_run(
        example=example,
        status=AgentRunStatus.COMPLETED,
    )
    synced_test_session.add(critic_run)
    synced_test_session.flush()

    for i in range(3):
        call_event = Event(
            agent_run_id=critic_run.agent_run_id,
            sequence_num=i * 2,
            event_type="tool_call",
            timestamp=datetime.now(UTC),
            payload=ToolCall(name=f"test_tool_{i}", args_json=f'{{"arg": {i}}}', call_id=f"call_{i}"),
        )
        synced_test_session.add(call_event)

        output_event = Event(
            agent_run_id=critic_run.agent_run_id,
            sequence_num=i * 2 + 1,
            event_type="tool_call_output",
            timestamp=datetime.now(UTC),
            payload=ToolCallOutput(
                call_id=f"call_{i}",
                result=CallToolResult(isError=False, content=[TextContent(type="text", text=f"result {i}")])
            ),
        )
        synced_test_session.add(output_event)

    grader_run = make_grader_run(critic_run=critic_run)
    synced_test_session.add(grader_run)

    synced_test_session.commit()

    expected_run_id_prefix = str(critic_run.agent_run_id)[:6]
    expected_definition_id = critic_run.agent_definition_id
    expected_snapshot = snapshot.slug

    show_execution_traces()

    captured = capsys.readouterr()
    output = captured.out

    assert "Recent critic runs" in output
    assert expected_run_id_prefix in output, f"Expected run ID prefix '{expected_run_id_prefix}' in output"
    assert expected_definition_id in output, f"Expected definition ID '{expected_definition_id}' in output"
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    assert "Snapshot:" in output
    assert "Definition:" in output
    assert "Status:" in output
    assert "Tools:" in output
    assert "completed" in output
    assert "Tools: 3" in output
    assert "Trace for" in output
    assert "tool" in output
    assert "test_tool_0" in output
    assert "result 0" in output


def test_show_execution_traces_empty_database(test_db: DatabaseConfig, capsys):
    """Test that show_execution_traces handles empty database gracefully."""
    show_execution_traces()

    captured = capsys.readouterr()
    output = captured.out

    assert "Recent critic runs" in output


def test_analyze_critic_failure_with_data(synced_test_session: Session, capsys):
    """Test that analyze_critic_failure displays critic run data correctly."""
    slug = SnapshotSlug("test-fixtures/test-trivial")
    example = synced_test_session.query(Example).filter_by(snapshot_slug=slug).first()
    assert example, "test-trivial fixture not found"

    critic_run = make_critic_run(
        example=example,
        status=AgentRunStatus.COMPLETED,
    )
    synced_test_session.add(critic_run)
    synced_test_session.flush()

    grader_run = make_grader_run(
        critic_run=critic_run,
    )
    synced_test_session.add(grader_run)
    synced_test_session.commit()

    # Access scope_hash directly from Pydantic model
    if isinstance(critic_run.type_config, CriticTypeConfig):
        test_scope_hash = critic_run.type_config.scope_hash
    else:
        raise ValueError(f"Expected CriticTypeConfig, got {type(critic_run.type_config)}")

    # Call with actual values
    analyze_critic_failure(str(slug), test_scope_hash)

    captured = capsys.readouterr()
    output = captured.out

    assert "critic runs for" in output
    assert "Definition:" in output


def test_analyze_critic_failure_no_data(test_db: DatabaseConfig, capsys):
    """Test that analyze_critic_failure handles missing critic runs gracefully."""
    # Use a fake example that doesn't exist
    analyze_critic_failure("nonexistent/2025-01-01-00", "0" * 64)

    captured = capsys.readouterr()
    output = captured.out

    assert "No critic runs found" in output
