"""Tests for the query_execution_traces example script."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from tests.props.conftest import make_critic_run, make_grader_output, make_grader_run

from adgn.agent.events import ToolCall, ToolCallOutput
from mcp.types import CallToolResult, TextContent
from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus, Event, Snapshot
from adgn.props.db.examples import Example
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.snapshots import DBCriticSubmitPayload, DBCriticSuccess

def test_query_execution_traces_with_data(synced_test_fixtures, mock_agent_setup, capsys, test_prompt_sha):
    """Test that query_execution_traces produces reasonable output with run data."""
    from adgn.props.examples.query_execution_traces import main  # noqa: PLC0415

    # Create test data
    with get_session() as session:
        # Get a snapshot from synced data (test-trivial or test-validation)
        snapshot = session.query(Snapshot).first()
        assert snapshot, "Expected snapshots from test fixtures"

        # Get an example
        example = session.query(Example).filter_by(snapshot_slug=snapshot.slug).first()
        assert example, "Expected examples from test fixtures"

        # Create a critic run with proper output (using helper)
        transcript_id = uuid4()
        payload = DBCriticSubmitPayload(notes_md=None)
        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            transcript_id=transcript_id,
            output=DBCriticSuccess(result=payload),
            status=CriticRunStatus.COMPLETED,
        )
        session.add(critic_run)
        session.flush()

        # Add some tool call events with proper typed payloads
        for i in range(3):
            # Tool call event
            call_event = Event(
                transcript_id=transcript_id,
                sequence_num=i * 2,
                event_type="tool_call",
                timestamp=datetime.now(UTC),
                payload=ToolCall(name=f"test_tool_{i}", args_json=f'{{"arg": {i}}}', call_id=f"call_{i}"),
            )
            session.add(call_event)

            # Tool output event
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

        # Create a grader run with 85% recall (found_credit = 0.85)
        grader_run = make_grader_run(
            critic_run=critic_run,
            output=make_grader_output(tp_count=1, found_credit=0.85, summary="Test summary for grader run"),
        )
        session.add(grader_run)

        session.commit()

        # Remember details for verification (access after commit)
        expected_run_id_prefix = str(critic_run.id)[:6]  # short_sha returns 6 chars
        expected_prompt_prefix = test_prompt_sha[:6]
        expected_snapshot = snapshot.slug

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Recent critic runs" in output

    # Verify specific data appears
    assert expected_run_id_prefix in output, f"Expected run ID prefix '{expected_run_id_prefix}' in output"
    assert expected_prompt_prefix in output, f"Expected prompt hash prefix '{expected_prompt_prefix}' in output"
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"

    # Verify run details sections appear
    assert "Snapshot:" in output, "Expected 'Snapshot:' label in output"
    assert "Prompt:" in output, "Expected 'Prompt:' label in output"
    assert "Status:" in output, "Expected 'Status:' label in output"
    assert "Tool calls:" in output, "Expected 'Tool calls:' label in output"

    # Verify status shows "success"
    assert "success" in output, "Expected status 'success' in output"

    # Verify tool call count shows
    assert "Tool calls: 3" in output, "Expected 'Tool calls: 3' in output"

    # Verify detailed execution trace shows event types and content
    assert "Execution trace for run" in output, "Expected 'Execution trace for run' section"
    # Event types may be truncated in table display (e.g., "tool…" for tool_call/tool_call_output)
    assert "tool" in output, "Expected 'tool' event type in output"
    assert "test_tool_0" in output, "Expected tool name 'test_tool_0' in output"
    assert "result 0" in output, "Expected tool output 'result 0' in output"

def test_query_execution_traces_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_execution_traces handles empty database gracefully."""
    from adgn.props.examples.query_execution_traces import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header even with no data
    assert "Recent critic runs" in output
