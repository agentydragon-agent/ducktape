"""Tests for the query_execution_traces example script."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.critic.persistence import critic_submit_payload_to_db
from adgn.props.db import get_session
from adgn.props.db.models import Critique, CriticRun, Event, Example, GraderRun, Prompt, Snapshot
from adgn.props.db.snapshots import DBCriticSuccess
from tests.props.conftest import make_grader_output


def test_query_execution_traces_with_data(synced_test_db, capsys):
    """Test that query_execution_traces produces reasonable output with run data."""
    from adgn.props.examples.query_execution_traces import main

    # Create test data
    with get_session() as session:
        # Get a snapshot from synced data
        snapshot = session.query(Snapshot).first()
        if not snapshot:
            pytest.skip("No snapshots in synced_test_db")

        # Get an example
        example = session.query(Example).filter_by(snapshot_slug=snapshot.slug).first()
        if not example:
            pytest.skip("No examples for snapshot in synced_test_db")

        # Create a prompt
        prompt = Prompt(prompt_sha256="test" + "a" * 60, prompt_text="Test prompt for execution traces")
        session.add(prompt)
        session.flush()

        # Create a critique
        payload = critic_submit_payload_to_db(CriticSubmitPayload(issues=[], notes_md=None))
        critique = Critique(snapshot_slug=snapshot.slug, payload=payload)
        session.add(critique)
        session.flush()

        # Create a critic run with proper output
        critic_run_id = uuid4()
        transcript_id = uuid4()
        critic_run = CriticRun(
            id=critic_run_id,
            transcript_id=transcript_id,
            prompt_sha256=prompt.prompt_sha256,
            snapshot_slug=snapshot.slug,
            model="test-model",
            critique_id=critique.id,
            files=example.files,
            files_hash=example.files_hash,
            output=DBCriticSuccess(result=payload),
        )
        session.add(critic_run)
        session.flush()

        # Add some tool call events
        from datetime import datetime, timezone

        for i in range(3):
            event = Event(
                transcript_id=transcript_id,
                sequence_num=i,
                event_type="tool_call",
                timestamp=datetime.now(timezone.utc),
                payload={"name": f"test_tool_{i}", "args": {}},
            )
            session.add(event)

        # Create a grader run
        grader_run = GraderRun(
            id=uuid4(),
            transcript_id=uuid4(),
            snapshot_slug=snapshot.slug,
            model="test-model",
            critique_id=critique.id,
            canonical_issues_snapshot={"true_positives": [], "false_positives": []},
            output=make_grader_output(tp_count=0, fp_count=0, recall=0.85, tp_ratio=0.0, fp_ratio=0.0, summary="Test summary for grader run"),
        )
        session.add(grader_run)

        session.commit()

        # Remember details for verification
        expected_run_id_prefix = str(critic_run_id)[:8]
        expected_prompt_prefix = prompt.prompt_sha256[:8]
        expected_snapshot = snapshot.slug

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_execution_traces.setup_agent_database"):
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

    # Verify recall shows
    assert "Recall:" in output, "Expected 'Recall:' in output"
    assert "85.0%" in output, "Expected recall '85.0%' in output"


def test_query_execution_traces_empty_database(test_db, capsys):
    """Test that query_execution_traces handles empty database gracefully."""
    from adgn.props.examples.query_execution_traces import main

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_execution_traces.setup_agent_database"):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header even with no data
    assert "Recent critic runs" in output
