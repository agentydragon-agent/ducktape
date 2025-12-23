"""Helper usage examples for interactive grading.

This shows how to use the decision helper functions during interactive grading.
The grader agent reviews each input issue manually and calls these functions as needed.

Prerequisites:
- Database credentials are set via PG* environment variables (automatic from temporary user)
- grader_run_id is accessible via current_grader_run_id() SQL function (RLS scoping)
- Database schema docs available in /workspace/docs/db/ (see evaluation_flow.md, grading.md)
"""

from __future__ import annotations

from sqlalchemy import text

from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, FalsePositive, ReportedIssue, TruePositive
from adgn.props.grader.decision_helpers import insert_fp_match, insert_no_match, insert_tp_match

# ============================================================================
# Example 1: Loading ground truth to review
# ============================================================================


def load_ground_truth_example():
    """Load and review ground truth issues."""
    snapshot_slug = "example/snapshot-slug"

    with get_session() as session:
        # Get all true positives
        tps = session.query(TruePositive).filter_by(snapshot_slug=snapshot_slug).all()

        # Get all false positives
        fps = session.query(FalsePositive).filter_by(snapshot_slug=snapshot_slug).all()

        # Review them manually
        print(f"Ground truth TPs ({len(tps)} total):")
        for tp in tps:
            print(f"  {tp.tp_id}: {tp.rationale}")
            # tp.occurrences contains location details

        print(f"\nGround truth FPs ({len(fps)} total):")
        for fp in fps:
            print(f"  {fp.fp_id}: {fp.rationale}")


# ============================================================================
# Example 2: Loading critic run reported issues to grade
# ============================================================================


def load_critique_example():
    """Load input issues from the critic run's reported issues."""
    critic_run_id = "123e4567-e89b-12d3-a456-426614174000"  # Example UUID

    with get_session() as session:
        critic_run = session.get(AgentRun, critic_run_id)
        if not critic_run:
            raise ValueError(f"Agent run {critic_run_id} not found")

        # Load reported issues from normalized table
        reported_issues = session.query(ReportedIssue).filter_by(agent_run_id=critic_run_id).all()

        # Review input issues manually
        print(f"Input issues to grade ({len(reported_issues)} total):")
        for issue in reported_issues:
            print(f"\n  Input ID: {issue.issue_id}")
            print(f"  Rationale: {issue.rationale}")
            print(f"  Occurrences: {len(issue.occurrences)}")
            for occ in issue.occurrences:
                for loc in occ.locations:
                    if loc.start_line is not None and loc.end_line is not None:
                        end_str = f"-{loc.end_line}" if loc.end_line != loc.start_line else ""
                        print(f"    - {loc.file}:{loc.start_line}{end_str}")
                    else:
                        print(f"    - {loc.file} (whole file)")


# ============================================================================
# Example 3: Grading decisions - TP match
# ============================================================================


def example_tp_match():
    """After reviewing, you determined input-001 matches tp-042."""
    # You manually reviewed the input and ground truth
    # You determined this is a semantic match worth 0.9 credit

    insert_tp_match(
        input_issue_id="input-001",
        tp_id="tp-042",
        tp_occurrence_id="occ-001",
        credit=0.9,
        rationale="Describes same dead code issue in server.py, slightly less specific than canonical",
    )


# ============================================================================
# Example 4: Grading decisions - FP match
# ============================================================================


def example_fp_match():
    """After reviewing, you determined input-003 triggered a known FP pattern."""
    # You manually reviewed the input
    # You noticed it matches a known acceptable pattern (false positive)

    insert_fp_match(
        input_issue_id="input-003",
        fp_id="fp-015",
        fp_occurrence_id="occ-001",
        rationale="Input flagged UI component duplication, but this is known acceptable for visual consistency",
    )


# ============================================================================
# Example 5: Grading decisions - No match
# ============================================================================


def example_no_match():
    """After reviewing, you determined input-099 is novel (not in ground truth)."""
    # You manually reviewed the input
    # You searched ground truth TPs and FPs
    # No match found - this is a novel finding

    insert_no_match(
        input_issue_id="input-099",
        rationale="Novel architectural suggestion about using dependency injection. "
        "Valid concern but not in ground truth TPs.",
    )


# ============================================================================
# Example 6: Checking progress
# ============================================================================


def check_progress_example():
    """Check how many inputs have been graded so far."""
    with get_session() as session:
        # Count decisions made
        count = session.execute(
            text("SELECT COUNT(*) FROM grading_decisions WHERE grader_run_id = current_grader_run_id()")
        ).scalar()

        print(f"Decisions made so far: {count}")

        # Check which inputs still need grading by comparing against reported issues


# ============================================================================
# Interactive Workflow Summary
# ============================================================================

"""
Typical interactive grading workflow:

1. Load and review ground truth:
   - Query TruePositive and FalsePositive tables
   - Read rationales and locations for each canonical issue

2. Load and review critique:
   - Query ReportedIssue table to get input issues
   - Read input rationales and locations

3. For each input issue (one at a time):
   a. Read the input's rationale and locations
   b. Search ground truth TPs for semantic matches
   c. Consider location overlap and description similarity
   d. Make a grading decision:
      - TP match -> insert_tp_match() with appropriate credit
      - FP match -> insert_fp_match()
      - No match -> insert_no_match()

4. After grading ALL inputs:
   - Call grader_submit(summary="...") via MCP to complete

Key point: You're making manual judgments at each step, not automating the grading.
The helper functions just make it easy to record your decisions.
"""
