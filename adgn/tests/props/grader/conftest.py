"""Fixtures and helpers for grader tests.

Note: Decision insertion helpers have been moved to production code.
Import from adgn.props.grader.decision_helpers instead.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, CriticRunStatus, ReportedIssue
from adgn.props.db.snapshots import DBGraderOutput, DBReportedIssue
from adgn.props.grader.decision_helpers import insert_fp_match, insert_no_match, insert_tp_match
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope
from tests.props.conftest import get_example, make_critic_run, make_grader_output, make_grader_run
from tests.support.responses import ResponsesFactory

__all__ = [
    "insert_fp_match",
    "insert_no_match",
    "insert_tp_match",
    "make_test_critic_run",
    "make_test_grader_run",
    "test_grader_critic_run",
    "test_grader_run",
]


def make_test_critic_run(example: Example, prompt_sha256: str, num_issues: int = 1) -> UUID:  # type: ignore[return]
    """Create a test critic run with specified number of input issues.

    Args:
        example: Example object (snapshot + scope)
        prompt_sha256: Prompt SHA256
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
        critic_run = make_critic_run(example=example, prompt_sha256=prompt_sha256, status=CriticRunStatus.COMPLETED)
        session.add(critic_run)
        session.flush()

        # Populate normalized reported_issues table
        for issue in issues:
            reported_issue = ReportedIssue(critic_run_id=critic_run.id, issue_id=issue.id, rationale=issue.rationale)
            session.add(reported_issue)

        session.commit()

        # Explicitly type the return value to help mypy
        critic_run_id: UUID = critic_run.id
        return critic_run_id


def make_test_grader_run(
    snapshot_slug: str | SnapshotSlug, critic_run_id: UUID, output: DBGraderOutput | None = None
) -> UUID:
    """Create a test grader run.

    Args:
        snapshot_slug: Snapshot slug (kept for backward compatibility, but derived from critic_run)
        critic_run_id: Critic run ID
        output: Grader output dict (default: success with 0 TPs)

    Returns:
        grader_run_id (UUID)
    """
    if output is None:
        output = make_grader_output(tp_count=0, summary="Test grader")

    with get_session() as session:
        # Fetch the critic_run to pass to factory
        critic_run = session.query(CriticRun).filter_by(id=critic_run_id).one()

        # Use centralized factory
        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)
        session.commit()
        return grader_run.id


# =============================================================================
# Shared test fixtures (used by multiple test files)
# =============================================================================


@pytest.fixture
def zero_issues_critic_input(test_snapshot, test_prompt_sha, subtract_file_scope):
    """Critic input for zero-issues test scenario."""
    return CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)


@pytest.fixture
def zero_issues_critic_responses(make_openai_client):
    """Mock critic client for zero-issues scenario (HTTP mode).

    Uses CLI helper: adgn-properties agent-helper critic submit
    """
    factory = ResponsesFactory("gpt-5-nano")
    responses = [
        # Use CLI helper to submit zero issues
        factory.make(
            factory.docker_exec(
                ["adgn-properties", "agent-helper", "critic", "submit", "0", "Reviewed code, no issues found"],
                timeout_ms=15000,
            )
        )
    ]
    return make_openai_client(responses)


@pytest.fixture
def test_grader_critic_run(test_db, test_snapshot, test_prompt_sha):
    """Create test critic run with 3 input issues.

    Returns:
        critic_run_id (UUID)
    """
    # Get example from git fixtures
    with get_session() as session:
        example = get_example(session, test_snapshot, AllFilesScope())
    return make_test_critic_run(example, test_prompt_sha, num_issues=3)


@pytest.fixture
def test_grader_run(test_db, test_snapshot, test_grader_critic_run):
    """Create test grader run.

    Returns:
        grader_run_id (UUID)
    """
    return make_test_grader_run(test_snapshot, test_grader_critic_run)
