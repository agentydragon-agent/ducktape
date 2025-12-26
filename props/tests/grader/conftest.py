"""Fixtures and helpers for grader tests.

Note: Decision insertion helpers have been moved to production code.
Import from props.grader.decision_helpers instead.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from props.db.examples import Example
from props.db.models import AgentRun, AgentRunStatus, ReportedIssue
from props.db.session import get_session
from props.db.snapshots import DBGraderOutput, DBReportedIssue
from props.grader.decision_helpers import insert_fp_match, insert_no_match, insert_tp_match
from props.ids import SnapshotSlug
from props.models.examples import WholeSnapshotExample
from tests.conftest import make_critic_run, make_grader_output, make_grader_run

__all__ = [
    "insert_fp_match",
    "insert_no_match",
    "insert_tp_match",
    "make_test_critic_run",
    "make_test_grader_run",
    "test_grader_critic_run",
    "test_grader_run",
]


def make_test_critic_run(example: Example, num_issues: int = 1) -> UUID:  # type: ignore[return]
    """Create a test critic run with specified number of input issues.

    Args:
        example: Example object (snapshot + scope)
        num_issues: Number of input issues to create (default: 1)

    Returns:
        critic_run_id (UUID)
    """

    with get_session() as session:
        # Merge example into this session if it's detached from another session
        example = session.merge(example)

        # Build list of issues to populate normalized tables
        issues = [
            DBReportedIssue(id=f"input-{i:03d}", rationale=f"Test input issue {i}", occurrences=[])
            for i in range(1, num_issues + 1)
        ]
        # Payload only contains notes_md (issues are in normalized table)

        # Create critic run with full output
        critic_run = make_critic_run(example=example, status=AgentRunStatus.COMPLETED)
        session.add(critic_run)
        session.flush()

        # Populate normalized reported_issues table
        for issue in issues:
            reported_issue = ReportedIssue(
                agent_run_id=critic_run.agent_run_id, issue_id=issue.id, rationale=issue.rationale
            )
            session.add(reported_issue)

        session.commit()

        # Explicitly type the return value to help mypy
        critic_run_id: UUID = critic_run.agent_run_id
        return critic_run_id


def make_test_grader_run(
    snapshot_slug: str | SnapshotSlug,
    critic_run_id: UUID,
    output: DBGraderOutput | None = None,
    status: AgentRunStatus | None = None,
) -> UUID:
    """Create a test grader run.

    Args:
        snapshot_slug: Snapshot slug (kept for backward compatibility, but derived from critic_run)
        critic_run_id: Critic run ID
        output: Grader output dict (default: success with 0 TPs)
        status: Run status (default: COMPLETED for compatibility)

    Returns:
        grader_run_id (UUID)
    """
    if output is None:
        output = make_grader_output(tp_occurrences=[], summary="Test grader")

    if status is None:
        status = AgentRunStatus.COMPLETED

    with get_session() as session:
        # Fetch the critic_run to pass to factory
        critic_run = session.query(AgentRun).filter_by(agent_run_id=critic_run_id).one()

        # Use centralized factory
        grader_run = make_grader_run(critic_run=critic_run, status=status)
        session.add(grader_run)
        session.commit()
        return grader_run.agent_run_id


# =============================================================================
# Shared test fixtures (used by multiple test files)
# =============================================================================


@pytest.fixture
def test_grader_critic_run(test_db, test_snapshot):
    """Create test critic run with 3 input issues.

    Returns:
        critic_run_id (UUID)
    """
    # Get example from git fixtures
    with get_session() as session:
        example = Example.from_spec(session, WholeSnapshotExample(snapshot_slug=test_snapshot))
    return make_test_critic_run(example, num_issues=3)


@pytest.fixture
def test_grader_run(test_db, test_snapshot, test_grader_critic_run):
    """Create test grader run in IN_PROGRESS status.

    Returns:
        grader_run_id (UUID)
    """
    return make_test_grader_run(test_snapshot, test_grader_critic_run, status=AgentRunStatus.IN_PROGRESS)
