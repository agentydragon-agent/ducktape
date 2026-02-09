"""E2E test for snapshot grader.

Tests that the snapshot grader:
1. Detects pending drift in grading_pending view
2. Picks up new critique issues and grades them
3. Creates GradingEdge records
4. Clusters unmatched issues (credit=0)

Test flow:
- Insert drift data (completed critic run with reported issues) BEFORE starting grader
- Start snapshot grader container (runs indefinitely)
- Grader finds drift on first check, grades the issues, creates GradingEdge
- Grader clusters unmatched issues, then sleeps
- Assert no drift remains (grading + clustering)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from uuid import UUID, uuid4

import pytest
import pytest_bazel

from agent_core.testing.responses import PlayGen
from props.agents.grader.drift_handler import check_all_pending, check_grading_pending
from props.agents.grader.testing.mocks import GraderMock
from props.agents.grader.tools import ClusterMemberSpec
from props.db.database import Database
from props.db.models import AgentRunStatus, GradingEdge, IssueCluster, ReportedIssue, ReportedIssueOccurrence
from props.db.snapshots import DBLocationAnchor
from props.testing.constants import DEFAULT_TEST_MODEL
from props.testing.fixtures.runs import make_fake_critic_run

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


@pytest.mark.timeout(180)
async def test_grader_picks_up_drift(e2e_stack, test_snapshot, all_files_scope, grader_image, db: Database):
    """Test that snapshot grader detects, grades, and clusters new critique issues."""

    grading_done = asyncio.Event()

    @GraderMock.mock(check_consumed=False)  # Grader may be aborted before consuming all
    def mock(m: GraderMock) -> PlayGen:
        yield None  # First request

        # List pending items
        pending = yield from m.list_pending_roundtrip()
        logger.info(f"Grader found {len(pending)} pending items")

        # Group by (run_id, issue_id) and fill each group at once
        by_issue: dict[tuple[UUID, str], int] = defaultdict(int)
        for edge in pending:
            by_issue[(edge.critique_run_id, edge.critique_issue_id)] += 1

        for (run_id, issue_id), count in by_issue.items():
            logger.info(f"Grading {count} edges for issue {issue_id} from run {run_id}")
            yield from m.fill_remaining_roundtrip(run_id, issue_id, count, "No matching ground truth")

        # Cluster unmatched issues
        clustering_pending = yield from m.list_clustering_pending_roundtrip()
        logger.info(f"Grader found {len(clustering_pending)} issues needing clustering")

        if clustering_pending:
            members = [
                ClusterMemberSpec(run=cp.critique_run_id, issue_id=cp.critique_issue_id, rationale="Novel issue")
                for cp in clustering_pending
            ]
            yield from m.create_cluster_roundtrip("novel-issues", "Novel issues not in ground truth", members)

        grading_done.set()
        yield m.sleep("Graded and clustered all pending")

    async with e2e_stack({DEFAULT_TEST_MODEL: mock}, images=[grader_image]) as stack:
        # Create drift BEFORE starting grader so it finds drift on first check.
        critic_run_id = uuid4()
        with db.session() as session:
            critic_run = make_fake_critic_run(
                session=session,
                example=all_files_scope,
                model=stack.model,
                status=AgentRunStatus.EXITED,
                agent_run_id=critic_run_id,
            )
            session.add(critic_run)
            session.flush()

            issue = ReportedIssue(
                agent_run_id=critic_run_id, issue_id="test-issue-1", rationale="Test issue for grader e2e"
            )
            session.add(issue)
            session.add(
                ReportedIssueOccurrence(
                    agent_run_id=critic_run_id,
                    reported_issue_id="test-issue-1",
                    locations=[DBLocationAnchor(file="subtract.py", start_line=1, end_line=1)],
                )
            )
            session.commit()

            logger.info(f"Created critic run {critic_run_id} with reported issue")

        # Precondition: verify grading_pending has rows before starting grader
        pending_count = check_grading_pending(test_snapshot, db)
        assert pending_count > 0, f"grading_pending should have rows but has {pending_count}"

        # Start snapshot grader in background task
        grader_task = asyncio.create_task(
            stack.registry.run_snapshot_grader(snapshot_slug=test_snapshot, model=stack.model), name="snapshot-grader"
        )

        # Wait for grading + clustering to complete
        try:
            await asyncio.wait_for(grading_done.wait(), timeout=90)
        except TimeoutError:
            if grader_task.done():
                exc = grader_task.exception()
                if exc:
                    raise RuntimeError(f"Snapshot grader failed: {exc}") from exc
            raise AssertionError("Grading did not complete within timeout")

        # Cancel grader
        grader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await grader_task

        # Assert grading happened
        with db.session() as session:
            grading_edge = (
                session.query(GradingEdge)
                .filter_by(critique_run_id=critic_run_id, critique_issue_id="test-issue-1")
                .first()
            )
            assert grading_edge is not None, "GradingEdge was not created"
            assert grading_edge.credit == 0.0
            assert grading_edge.rationale is not None
            assert "No matching ground truth" in grading_edge.rationale

        # Assert clustering happened
        with db.session() as session:
            cluster = session.query(IssueCluster).filter_by(snapshot_slug=test_snapshot).first()
            assert cluster is not None, "Issue cluster was not created"

        # Assert no drift remains (grading + clustering)
        assert check_all_pending(test_snapshot, db) == 0, "Drift should be zero after grading + clustering"


if __name__ == "__main__":
    pytest_bazel.main()
