"""Tests for the query_top_prompts example script."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from adgn.props.critic.persistence import critic_submit_payload_to_db
from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import Critique, CriticRun, Example, GraderRun, Prompt, Snapshot
from adgn.props.ids import SnapshotSlug
from tests.props.conftest import make_grader_output


def test_query_top_prompts_with_synced_data(synced_test_db, capsys):
    """Test that query_top_prompts produces reasonable output with validation runs.

    Creates a few test validation runs to verify the query returns data in the expected format.
    """
    from adgn.props.examples.query_top_prompts import main

    # Create test data: 2 prompts with different recall on validation examples
    with get_session() as session:
        # Get validation examples from synced data
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .limit(2)
            .all()
        )

        if len(valid_examples) < 2:
            pytest.skip("Not enough validation examples in synced_test_db")

        # Create two prompts
        prompt_good = Prompt(prompt_sha256="a" * 64, prompt_text="Good prompt for testing")
        prompt_bad = Prompt(prompt_sha256="b" * 64, prompt_text="Bad prompt for testing")
        session.add_all([prompt_good, prompt_bad])
        session.flush()

        # Create runs for good prompt (high recall: 0.9, 0.8)
        for example, recall in zip(valid_examples, [0.9, 0.8]):
            payload = critic_submit_payload_to_db(CriticSubmitPayload(issues=[], notes_md=None))
            critique = Critique(snapshot_slug=example.snapshot_slug, payload=payload)
            session.add(critique)
            session.flush()

            critic_run = CriticRun(
                id=uuid4(),
                transcript_id=uuid4(),
                prompt_sha256=prompt_good.prompt_sha256,
                snapshot_slug=example.snapshot_slug,
                model="test-model",
                critique_id=critique.id,
                files=example.files,
                files_hash=example.files_hash,
                output={},
            )
            session.add(critic_run)
            session.flush()

            grader_run = GraderRun(
                id=uuid4(),
                transcript_id=uuid4(),
                snapshot_slug=example.snapshot_slug,
                model="test-model",
                critique_id=critique.id,
                canonical_issues_snapshot={"true_positives": [], "false_positives": []},
                output=make_grader_output(
                    tp_count=0, fp_count=0, recall=recall, tp_ratio=0.0, fp_ratio=0.0, summary="Test summary"
                ),
            )
            session.add(grader_run)

        # Create run for bad prompt (low recall: 0.2)
        payload_bad = critic_submit_payload_to_db(CriticSubmitPayload(issues=[], notes_md=None))
        critique_bad = Critique(snapshot_slug=valid_examples[0].snapshot_slug, payload=payload_bad)
        session.add(critique_bad)
        session.flush()

        critic_run_bad = CriticRun(
            id=uuid4(),
            transcript_id=uuid4(),
            prompt_sha256=prompt_bad.prompt_sha256,
            snapshot_slug=valid_examples[0].snapshot_slug,
            model="test-model",
            critique_id=critique_bad.id,
            files=valid_examples[0].files,
            files_hash=valid_examples[0].files_hash,
            output={},
        )
        session.add(critic_run_bad)
        session.flush()

        grader_run_bad = GraderRun(
            id=uuid4(),
            transcript_id=uuid4(),
            snapshot_slug=valid_examples[0].snapshot_slug,
            model="test-model",
            critique_id=critique_bad.id,
            canonical_issues_snapshot={"true_positives": [], "false_positives": []},
            output=make_grader_output(
                tp_count=0, fp_count=0, recall=0.2, tp_ratio=0.0, fp_ratio=0.0, summary="Test summary"
            ),
        )
        session.add(grader_run_bad)

        session.commit()

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_top_prompts.setup_agent_database"):
        main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Top 10 prompts on validation:" in output

    lines = output.strip().split("\n")

    # Should have header + 2 prompt lines (good and bad)
    assert len(lines) == 3, f"Expected 3 lines (header + 2 prompts), got {len(lines)}: {lines}"

    # Verify good prompt appears first (higher recall)
    assert "aaaaaaa" in lines[1], f"Expected good prompt first, got: {lines[1]}"
    assert "bbbbbbb" in lines[2], f"Expected bad prompt second, got: {lines[2]}"

    # Verify recall values
    assert "0.850" in lines[1], f"Expected mean recall 0.850 for good prompt: {lines[1]}"
    assert "0.200" in lines[2], f"Expected recall 0.200 for bad prompt: {lines[2]}"


def test_query_top_prompts_empty_database(test_db, capsys):
    """Test that query_top_prompts handles empty database gracefully."""
    from adgn.props.examples.query_top_prompts import main

    # Mock setup_agent_database since test_db already initialized the connection
    with patch("adgn.props.examples.query_top_prompts.setup_agent_database"):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header but no prompt lines
    assert "Top 10 prompts on validation:" in output
    # No data lines (just the header)
    lines = output.strip().split("\n")
    assert len(lines) == 1  # Just the header line
