"""Helper functions for inserting grading decisions and submitting gradings.

These helpers simplify the grading workflow by providing typed interfaces
for the three types of grading decisions: TP matches, FP matches, and no-matches.

Database session is obtained automatically using get_session() which respects
the grader agent's RLS-scoped credentials. The grader_run_id is automatically
set via database DEFAULT using current_grader_run_id() function.

Typical workflow:
    1. Call insert_tp_match(), insert_fp_match(), or insert_no_match() for each input issue
    2. Call submit_grading() to finalize and mark the grading complete
"""

from __future__ import annotations

from props_core.db.models import GradingDecision
from props_core.db.session import get_session

from agent_pkg_runtime.mcp import mcp_client_from_env


def insert_tp_match(input_issue_id: str, tp_id: str, tp_occurrence_id: str, credit: float, rationale: str) -> None:
    """Insert a grading decision matching an input issue to a true positive.

    Args:
        input_issue_id: ID of the input issue from the critique
        tp_id: ID of the canonical true positive being matched
        tp_occurrence_id: ID of the specific TP occurrence
        credit: Credit amount (0.0-1.0) for partial matches
        rationale: Explanation of why this decision was made

    Example:
        from props_core.grader.decision_helpers import insert_tp_match

        # Full match (1.0 credit)
        insert_tp_match(
            input_issue_id="input-001",
            tp_id="tp-042",
            tp_occurrence_id="occ-001",
            credit=1.0,
            rationale="Exact match - same location and description"
        )

        # Partial match (less than 1.0 credit)
        insert_tp_match(
            input_issue_id="input-002",
            tp_id="tp-042",
            tp_occurrence_id="occ-002",
            credit=0.7,
            rationale="Same issue but less specific description"
        )
    """
    with get_session() as session:
        decision = GradingDecision(
            input_issue_id=input_issue_id,
            target_tp_id=tp_id,
            target_tp_occurrence_id=tp_occurrence_id,
            credit=credit,
            rationale=rationale,
            # grader_run_id set via server_default=current_grader_run_id()
        )
        session.add(decision)


def insert_fp_match(input_issue_id: str, fp_id: str, fp_occurrence_id: str, rationale: str) -> None:
    """Insert a grading decision matching an input issue to a false positive.

    FP matches indicate the input triggered a known acceptable pattern that should
    NOT be flagged as an issue. Credit is always 0.0 for FP matches.

    Args:
        input_issue_id: ID of the input issue from the critique
        fp_id: ID of the canonical false positive being matched
        fp_occurrence_id: ID of the specific FP occurrence
        rationale: Explanation of why this decision was made

    Example:
        from props_core.grader.decision_helpers import insert_fp_match

        insert_fp_match(
            input_issue_id="input-003",
            fp_id="fp-015",
            fp_occurrence_id="occ-001",
            rationale="Input matches known acceptable duplication pattern in UI components"
        )
    """
    with get_session() as session:
        decision = GradingDecision(
            input_issue_id=input_issue_id,
            target_fp_id=fp_id,
            target_fp_occurrence_id=fp_occurrence_id,
            credit=0.0,
            rationale=rationale,
        )
        session.add(decision)


def insert_no_match(input_issue_id: str, rationale: str) -> None:
    """Insert a grading decision for an input issue with no canonical match.

    No-match decisions indicate the input is a novel finding not present in the
    ground truth. Credit is always 0.0 for no-match decisions.

    Args:
        input_issue_id: ID of the input issue from the critique
        rationale: Explanation of why no match was found

    Example:
        from props_core.grader.decision_helpers import insert_no_match

        insert_no_match(
            input_issue_id="input-099",
            rationale="Novel architectural suggestion not in ground truth"
        )
    """
    with get_session() as session:
        decision = GradingDecision(input_issue_id=input_issue_id, credit=0.0, rationale=rationale)
        session.add(decision)


def delete_decision(input_issue_id: str) -> None:
    """Delete a grading decision for an input issue.

    Use this to remove an incorrect decision before inserting a corrected one.
    Hard delete - no soft delete/cancellation tracking.

    Args:
        input_issue_id: ID of the input issue whose decision should be deleted

    Example:
        from props_core.grader.decision_helpers import delete_decision

        # Delete an incorrect decision
        delete_decision(input_issue_id="input-002")

        # Then insert the corrected decision
        insert_tp_match(
            input_issue_id="input-002",
            tp_id="tp-042",
            tp_occurrence_id="occ-001",
            credit=1.0,
            rationale="Corrected decision after review"
        )
    """
    with get_session() as session:
        # Query for the decision to delete (RLS ensures we only see our run's decisions)
        decision = session.query(GradingDecision).filter_by(input_issue_id=input_issue_id).first()
        if decision:
            session.delete(decision)


async def submit_grading(summary: str) -> None:
    """Call the MCP submit tool to finalize the grading.

    This marks the grading as complete and validates that all input issues have been
    graded with decisions.

    Args:
        summary: Brief summary of the grading results

    Example:
        import asyncio
        from props_core.grader.decision_helpers import insert_tp_match, insert_no_match, submit_grading

        # Grade the inputs
        insert_tp_match("input-001", "tp-042", "occ-001", 1.0, "Exact match")
        insert_no_match("input-002", "Novel architectural suggestion")

        # Finalize
        asyncio.run(submit_grading(
            summary="Graded 2 inputs: 1 TP match, 1 novel finding"
        ))

    Note:
        This function is async and must be called with asyncio.run() or await.
        The MCP server will validate that all input issues have decisions.
    """
    async with mcp_client_from_env() as (client, _init_result):
        result = await client.call_tool("submit", {"summary": summary})
        if result.is_error:
            raise RuntimeError(f"Submit failed: {result.content}")
