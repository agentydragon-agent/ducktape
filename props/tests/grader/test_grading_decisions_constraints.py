"""Test SQL constraints on grading_decisions table.

Verifies that database constraints correctly enforce:
- Exactly ONE target type (TP / FP / no-match) via NULL pattern
- No-match decisions must have credit = 0.0
- Credit must be between 0.0 and 1.0
- Credit sum ≤1.0 per occurrence (enforced by SQL trigger)
- Soft delete semantics (cancelled_at)
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from props.db.models import GradingDecision
from props.db.session import get_session

# Fixtures providing real TP/FP occurrences from git-synced snapshots are defined in tests/props/conftest.py

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.fixture
def session(test_db):
    """Provide a database session for the test (depends on test_db initialization)."""
    with get_session() as sess:
        yield sess


@pytest.fixture
def add_decision(session, test_grader_run):
    """Fixture factory for creating grading decisions.

    Returns a function that creates and adds GradingDecision objects to the session.
    Automatically uses the test's session and grader_run.
    """

    def _add(input_issue_id, rationale="Test decision", **kwargs):
        decision = GradingDecision(
            agent_run_id=test_grader_run, input_issue_id=input_issue_id, rationale=rationale, **kwargs
        )
        session.add(decision)
        return decision

    return _add


def test_decision_tp_match_valid(session, add_decision, tp_occurrence_single):
    """Valid: TP match with both tp_id and tp_occurrence_id."""
    tp_id, occ_id = tp_occurrence_single
    add_decision("input-001", target_tp_id=tp_id, target_tp_occurrence_id=occ_id, credit=0.8, rationale="Matches TP")
    session.commit()  # Should succeed


def test_decision_fp_match_valid(session, add_decision, fp_occurrence):
    """Valid: FP match with both fp_id and fp_occurrence_id."""
    fp_id, fp_occ = fp_occurrence
    add_decision("input-002", target_fp_id=fp_id, target_fp_occurrence_id=fp_occ, credit=1.0, rationale="Matches FP")
    session.commit()  # Should succeed


def test_decision_no_match_valid(session, add_decision):
    """Valid: No-match with all targets NULL and credit=0.0."""
    add_decision("input-003", credit=0.0, rationale="No match in ground truth")
    session.commit()  # Should succeed


def test_decision_partial_tp_target_invalid(session, add_decision, tp_occurrence_single):
    """Invalid: TP match requires BOTH tp_id and tp_occurrence_id."""
    # Only tp_id, missing tp_occurrence_id
    tp_id, _ = tp_occurrence_single
    add_decision(
        "input-001",
        target_tp_id=tp_id,
        # Missing target_tp_occurrence_id
        credit=0.5,
        rationale="Invalid: incomplete TP target",
    )

    with pytest.raises(Exception, match="does not exist"):
        session.commit()
    session.rollback()


def test_decision_partial_fp_target_invalid(session, add_decision, fp_occurrence):
    """Invalid: FP match requires BOTH fp_id and fp_occurrence_id."""
    # Only fp_id, missing fp_occurrence_id
    fp_id, _ = fp_occurrence
    add_decision(
        "input-002",
        target_fp_id=fp_id,
        # Missing target_fp_occurrence_id
        credit=0.5,
        rationale="Invalid: incomplete FP target",
    )

    with pytest.raises(Exception, match="does not exist"):
        session.commit()
    session.rollback()


def test_decision_no_match_nonzero_credit_invalid(session, add_decision):
    """Invalid: No-match decisions must have credit=0.0."""
    # Uses fixture ID (input-003), all targets NULL (no-match)
    add_decision(
        "input-003",
        credit=0.5,  # Invalid: must be 0.0 for no-match
        rationale="Invalid: no-match with non-zero credit",
    )

    with pytest.raises(IntegrityError, match="no_match_zero_credit"):
        session.commit()
    session.rollback()


def test_decision_credit_range_valid(session, add_decision, tp_occurrences_multi, tp_occurrence_single):
    """Valid: credit can be any value between 0.0 and 1.0."""
    # Test boundary values - use different occurrences to avoid credit sum constraint
    # Use valid issue IDs (5-40 chars, lowercase alphanumeric, underscore, hyphen only)
    # Pull real occurrences; if we don't have 3 distinct ones, reuse the single tp_occurrence
    occs = tp_occurrences_multi[:3]
    if len(occs) < 3:
        occs = occs + [tp_occurrence_single] * (3 - len(occs))

    test_cases = [
        (0.0, "input-001", occs[0][0], occs[0][1]),
        (0.5, "input-002", occs[1][0], occs[1][1]),
        (1.0, "input-003", occs[2][0], occs[2][1]),
    ]
    for credit, issue_id, tp_id, occ_id in test_cases:
        add_decision(
            issue_id,
            target_tp_id=tp_id,
            target_tp_occurrence_id=occ_id,
            credit=credit,
            rationale=f"Valid credit: {credit}",
        )
    session.commit()  # Should succeed


def test_decision_credit_negative_invalid(session, add_decision, tp_occurrence_single):
    """Invalid: credit cannot be negative."""
    # Uses fixture ID (input-001)
    tp_id, occ_id = tp_occurrence_single
    add_decision(
        "input-001",
        target_tp_id=tp_id,
        target_tp_occurrence_id=occ_id,
        credit=-0.5,  # Invalid
        rationale="Invalid: negative credit",
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_decision_credit_above_one_invalid(session, add_decision, tp_occurrence_single):
    """Invalid: credit cannot exceed 1.0 (caught by trigger before CHECK constraint)."""
    # Uses fixture ID (input-002)
    tp_id, occ_id = tp_occurrence_single
    add_decision(
        "input-002",
        target_tp_id=tp_id,
        target_tp_occurrence_id=occ_id,
        credit=1.5,  # Invalid
        rationale="Invalid: credit > 1.0",
    )

    # Trigger catches this before CHECK constraint
    with pytest.raises(Exception, match=r"Credit sum would exceed 1\.0"):
        session.commit()
    session.rollback()


def test_credit_sum_trigger_enforces_limit_tp(session, add_decision, tp_occurrence_single):
    """SQL trigger enforces credit sum ≤1.0 per TP occurrence."""
    # First decision: 0.7 credit
    tp_id, occ_id = tp_occurrence_single
    add_decision(
        "input-001",  # Uses fixture ID
        target_tp_id=tp_id,
        target_tp_occurrence_id=occ_id,
        credit=0.7,
        rationale="First match",
    )
    session.commit()

    # Second decision: 0.5 credit (would exceed 1.0)
    add_decision(
        "input-002",  # Uses fixture ID
        target_tp_id=tp_id,  # Same occurrence
        target_tp_occurrence_id=occ_id,
        credit=0.5,  # Total would be 1.2 > 1.0
        rationale="Second match",
    )

    # SQL trigger should reject this
    with pytest.raises(Exception, match=r"Credit sum would exceed 1\.0"):
        session.commit()
    session.rollback()


def test_credit_sum_trigger_allows_exactly_one(session, add_decision, tp_occurrence_single):
    """SQL trigger allows credit sum = 1.0 (boundary case)."""
    # First decision: 0.6 credit
    tp_id, occ_id = tp_occurrence_single
    add_decision(
        "input-001",  # Uses fixture ID
        target_tp_id=tp_id,
        target_tp_occurrence_id=occ_id,
        credit=0.6,
        rationale="First match",
    )
    session.commit()

    # Second decision: 0.4 credit (exactly 1.0 total)
    add_decision(
        "input-002",  # Uses fixture ID
        target_tp_id=tp_id,  # Same occurrence
        target_tp_occurrence_id=occ_id,
        credit=0.4,  # Total = 1.0 (allowed)
        rationale="Second match",
    )
    session.commit()  # Should succeed


def test_credit_sum_trigger_enforces_limit_fp(session, add_decision, fp_occurrence):
    """SQL trigger enforces credit sum ≤1.0 per FP occurrence."""
    # First decision: 0.8 credit
    fp_id, fp_occ = fp_occurrence
    add_decision(
        "input-001",  # Uses fixture ID
        target_fp_id=fp_id,
        target_fp_occurrence_id=fp_occ,
        credit=0.8,
        rationale="First FP match",
    )
    session.commit()

    # Second decision: 0.3 credit (would exceed 1.0)
    add_decision(
        "input-002",  # Uses fixture ID
        target_fp_id=fp_id,  # Same FP occurrence
        target_fp_occurrence_id=fp_occ,
        credit=0.3,  # Total would be 1.1 > 1.0
        rationale="Second FP match",
    )

    # SQL trigger should reject this
    with pytest.raises(Exception, match=r"Credit sum would exceed 1\.0"):
        session.commit()
    session.rollback()
