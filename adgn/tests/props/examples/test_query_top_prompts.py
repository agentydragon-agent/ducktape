"""Tests for the query_top_prompts example script."""

from uuid import uuid4

import pytest
from tests.props.conftest import make_critic_and_grader_run, make_grader_output

from adgn.props.db import get_session
from adgn.props.db.models import CriticRunStatus, Snapshot
from adgn.props.db.examples import Example
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.snapshots import DBCriticSubmitPayload, DBCriticSuccess

def test_query_top_prompts_with_synced_data(synced_test_fixtures, mock_agent_setup, capsys):
    """Test that query_top_prompts produces reasonable output with validation runs.

    Creates a few test validation runs to verify the query returns data in the expected format.
    """
    from adgn.props.examples.query_top_prompts import main  # noqa: PLC0415

    # Create test data: 2 prompts with different recall on validation examples
    with get_session() as session:
        # Get validation per-file examples from synced data
        # (whole-snapshot examples use AllFilesScope)
        from adgn.props.models.critic_scopes import AllFilesScope
        all_valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "valid")
            .all()
        )
        # Filter to ExplicitFileScope examples only (not AllFilesScope), then take first 2
        valid_examples = [ex for ex in all_valid_examples if not isinstance(ex.scope, AllFilesScope)][:2]

        # synced_test_fixtures includes test-validation fixtures with per-file examples
        assert len(valid_examples) >= 2, f"Expected at least 2 valid ExplicitFileScope examples, got {len(valid_examples)}"

        # Create two prompts (helper computes proper hashes)
        prompt_good_sha = hash_and_upsert_prompt("Good prompt for testing")
        prompt_bad_sha = hash_and_upsert_prompt("Bad prompt for testing")

        # Create runs for good prompt (high recall: 0.9, 0.8)
        for example, recall in zip(valid_examples, [0.9, 0.8], strict=True):
            make_critic_and_grader_run(
                example=example,
                prompt_sha256=prompt_good_sha,
                grader_output=make_grader_output(found_credit=recall),
                session=session,
            )

        # Create run for bad prompt (low recall: 0.2)
        make_critic_and_grader_run(
            example=valid_examples[0],
            prompt_sha256=prompt_bad_sha,
            grader_output=make_grader_output(found_credit=0.2),
            session=session,
        )

        session.commit()

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Top 10 prompts on validation" in output

    lines = output.strip().split("\n")

    # Note: Since view groups by scope type, same prompt may appear multiple times
    # (once per scope type). The test creates runs on 2 per-file examples (ExplicitFileScope),
    # so we might see duplicates if examples have different scope types.
    # For simplicity, just verify the prompts and recall values appear in the output.

    # Extract hash prefixes from created prompts (first 6 chars to match short_sha())
    good_prompt_prefix = prompt_good_sha[:6]
    bad_prompt_prefix = prompt_bad_sha[:6]

    # Verify good prompt with high recall appears
    # Note: Recall is displayed as percentage (e.g., "85…" for 0.85), possibly truncated
    assert any(good_prompt_prefix in line and ("85" in line or "0.85" in line) for line in lines), (
        f"Expected good prompt ({good_prompt_prefix}) with recall ~0.85 in output: {lines}"
    )

    # Verify bad prompt with low recall appears
    assert any(bad_prompt_prefix in line and ("20" in line or "0.20" in line or "0.2" in line) for line in lines), (
        f"Expected bad prompt ({bad_prompt_prefix}) with recall ~0.20 in output: {lines}"
    )

    # Verify prompts are ordered by recall (good prompt lines should appear before bad prompt lines)
    good_indices = [i for i, line in enumerate(lines) if good_prompt_prefix in line]
    bad_indices = [i for i, line in enumerate(lines) if bad_prompt_prefix in line]
    assert all(g < b for g in good_indices for b in bad_indices), (
        f"Expected good prompt (indices {good_indices}) before bad prompt (indices {bad_indices})"
    )

def test_query_top_prompts_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_top_prompts handles empty database gracefully."""
    from adgn.props.examples.query_top_prompts import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header but no data rows
    assert "Top 10 prompts on validation" in output
    # Should show table structure (header + column headers + separator) but no data rows
    # Don't verify exact line count as table formatting may vary
