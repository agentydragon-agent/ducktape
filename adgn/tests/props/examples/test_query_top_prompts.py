"""Tests for the query_top_prompts example script."""

from uuid import uuid4

import pytest
from tests.props.conftest import make_grader_output

from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.critic.persistence import critic_submit_payload_to_db
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, Example, GraderRun, Prompt, Snapshot
from adgn.props.db.snapshots import DBCriticSuccess


def test_query_top_prompts_with_synced_data(synced_test_db, mock_agent_setup, capsys):
    """Test that query_top_prompts produces reasonable output with validation runs.

    Creates a few test validation runs to verify the query returns data in the expected format.
    """
    from adgn.props.examples.query_top_prompts import main  # noqa: PLC0415

    # Create test data: 2 prompts with different recall on validation examples
    with get_session() as session:
        # Get validation per-file examples from synced data
        # (whole-snapshot examples have files=NULL which requires special handling)
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .filter(Example.is_whole_snapshot == False)  # noqa: E712
            .filter(Example.files.isnot(None))  # Ensure resolved files list
            .limit(2)
            .all()
        )

        if len(valid_examples) < 2:
            pytest.skip("Not enough validation per-file examples in synced_test_db")

        # Create two prompts
        prompt_good = Prompt(prompt_sha256="a" * 64, prompt_text="Good prompt for testing")
        prompt_bad = Prompt(prompt_sha256="b" * 64, prompt_text="Bad prompt for testing")
        session.add_all([prompt_good, prompt_bad])
        session.flush()

        # Create runs for good prompt (high recall: 0.9, 0.8)
        for example, recall in zip(valid_examples, [0.9, 0.8], strict=True):
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
                output=DBCriticSuccess(result=payload),
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
                output=make_grader_output(found_credit=recall),
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
            output=DBCriticSuccess(result=payload_bad),
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
            output=make_grader_output(found_credit=0.2),
        )
        session.add(grader_run_bad)

        session.commit()

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Top 10 prompts on validation:" in output

    lines = output.strip().split("\n")

    # Note: Since view groups by is_whole_snapshot, same prompt may appear multiple times
    # (once per is_whole_snapshot value). The test creates runs on 2 per-file examples,
    # so we might see duplicates if examples have different is_whole_snapshot values.
    # For simplicity, just verify the prompts and recall values appear in the output.

    # Verify good prompt with high recall appears
    assert any("aaaaaaa" in line and "0.850" in line for line in lines), (
        f"Expected good prompt with recall 0.850 in output: {lines}"
    )

    # Verify bad prompt with low recall appears
    assert any("bbbbbbb" in line and "0.200" in line for line in lines), (
        f"Expected bad prompt with recall 0.200 in output: {lines}"
    )

    # Verify prompts are ordered by recall (good prompt lines should appear before bad prompt lines)
    good_indices = [i for i, line in enumerate(lines) if "aaaaaaa" in line]
    bad_indices = [i for i, line in enumerate(lines) if "bbbbbbb" in line]
    assert all(g < b for g in good_indices for b in bad_indices), (
        f"Expected good prompt (indices {good_indices}) before bad prompt (indices {bad_indices})"
    )


def test_query_top_prompts_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_top_prompts handles empty database gracefully."""
    from adgn.props.examples.query_top_prompts import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header but no prompt lines
    assert "Top 10 prompts on validation:" in output
    # No data lines (just the header)
    lines = output.strip().split("\n")
    assert len(lines) == 1  # Just the header line
