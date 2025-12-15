"""Integration test for clustering agent orchestration.

Tests the full orchestrator without running an actual LLM agent:
- Database setup (clustering run, snapshot, grader runs with unknowns)
- Completion detection handler
- Outcome computation
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from tests.props.conftest import make_grader_output

from adgn.props.clustering.cluster_agent import (
    ClusteringCompletionHandler,
    OutcomeIncomplete,
    OutcomeSuccess,
    _compute_outcome,
)
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.models import Critique, GraderRun, Snapshot
from adgn.props.db.snapshots import DBCriticSubmitPayload
from adgn.props.splits import Split


def make_test_snapshot(slug: str, commit: str) -> Snapshot:
    """Helper to create a test snapshot with standard git source."""
    return Snapshot(
        slug=slug, split=Split.TRAIN, source={"vcs": "git", "url": "https://example.com/repo.git", "commit": commit}
    )


def make_test_critique(snapshot_slug: str) -> Critique:
    """Helper to create a test critique with empty issues list."""
    return Critique(snapshot_slug=snapshot_slug, payload=DBCriticSubmitPayload(issues=[]))


def make_test_grader_run(snapshot_slug: str, critique_id: UUID, unknowns: list[dict]) -> GraderRun:
    """Helper to create a test grader run with unknowns.

    Args:
        snapshot_slug: Snapshot slug for the grader run
        critique_id: Critique ID being graded
        unknowns: List of unknown issue dicts with 'id' and 'rationale' keys
    """
    # Extract just the IDs for the fixture
    unknown_ids = [u["id"] for u in unknowns]

    return GraderRun(
        id=uuid4(),
        snapshot_slug=snapshot_slug,
        transcript_id=uuid4(),
        model="test-model",
        critique_id=critique_id,
        canonical_issues_snapshot={"true_positives": [], "false_positives": []},
        output=make_grader_output(tp_count=0, unknowns=unknown_ids),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_completion_handler_detects_all_assigned(test_db):
    """Test ClusteringCompletionHandler detects when all unknowns are assigned."""
    config = test_db

    # Setup: Create snapshot, clustering run, grader runs with unknowns
    with get_session() as session:
        snapshot = make_test_snapshot("test/completion", "abc123")
        session.add(snapshot)
        session.flush()
        snapshot_slug = snapshot.slug

        run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critique (needed for grader_run FK)
        critique = make_test_critique(snapshot_slug)
        session.add(critique)
        session.flush()
        critique_id = critique.id

        # Create grader run with 3 unknowns
        grader_run = make_test_grader_run(
            snapshot_slug,
            critique_id,
            unknowns=[
                {"id": "unknown-1", "rationale": "Issue 1"},
                {"id": "unknown-2", "rationale": "Issue 2"},
                {"id": "unknown-3", "rationale": "Issue 3"},
            ],
        )
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create cluster
        cluster = UnknownCluster(clustering_run_id=run_id, cluster_name="test-cluster", description="Test cluster")
        session.add(cluster)
        session.flush()

    # Test: Handler should return NoAction when not all assigned
    handler = ClusteringCompletionHandler(run_id, config)
    decision = handler.on_before_sample()
    assert decision.__class__.__name__ == "NoAction"

    # Assign 2 unknowns
    with get_session() as session:
        cluster_id = session.execute(
            select(UnknownCluster.id).where(UnknownCluster.clustering_run_id == run_id)
        ).scalar()

        for unknown_id in ["unknown-1", "unknown-2"]:
            assignment = UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id=unknown_id,
                cluster_id=cluster_id,
                rationale=f"Test assignment for {unknown_id}",
            )
            session.add(assignment)

    # Handler should still return NoAction (1 unknown remaining)
    decision = handler.on_before_sample()
    assert decision.__class__.__name__ == "NoAction"

    # Assign the last unknown
    with get_session() as session:
        cluster_id = session.execute(
            select(UnknownCluster.id).where(UnknownCluster.clustering_run_id == run_id)
        ).scalar()

        assignment = UnknownAssignment(
            clustering_run_id=run_id,
            grader_run_id=grader_run_id,
            unknown_id="unknown-3",
            cluster_id=cluster_id,
            rationale="Test assignment for unknown-3",
        )
        session.add(assignment)

    # Handler should now return Abort (all assigned)
    decision = handler.on_before_sample()
    assert decision.__class__.__name__ == "Abort"

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_completion_handler_no_unknowns(test_db):
    """Test ClusteringCompletionHandler aborts immediately when no unknowns exist."""
    config = test_db

    # Setup: Create snapshot and run with NO grader runs (no unknowns)
    with get_session() as session:
        snapshot = make_test_snapshot("test/no-unknowns", "def456")
        session.add(snapshot)
        session.flush()
        snapshot_slug = snapshot.slug

        run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id

    # Test: Handler should return Abort immediately (no unknowns to cluster)
    handler = ClusteringCompletionHandler(run_id, config)
    decision = handler.on_before_sample()
    assert decision.__class__.__name__ == "Abort"

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_compute_outcome_success(test_db):
    """Test _compute_outcome returns OutcomeSuccess when all unknowns assigned."""
    config = test_db

    # Setup: Create complete clustering run
    with get_session() as session:
        snapshot = make_test_snapshot("test/outcome-success", "ghi789")
        session.add(snapshot)
        session.flush()
        snapshot_slug = snapshot.slug

        run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critique (needed for grader_run FK)
        critique = make_test_critique(snapshot_slug)
        session.add(critique)
        session.flush()
        critique_id = critique.id

        # Create grader run with 2 unknowns
        grader_run = make_test_grader_run(
            snapshot_slug,
            critique_id,
            unknowns=[{"id": "unknown-a", "rationale": "Issue A"}, {"id": "unknown-b", "rationale": "Issue B"}],
        )
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create cluster
        cluster = UnknownCluster(clustering_run_id=run_id, cluster_name="test-cluster", description="Test cluster")
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id

        # Assign both unknowns to cluster
        for unknown_id in ["unknown-a", "unknown-b"]:
            assignment = UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id=unknown_id,
                cluster_id=cluster_id,
                rationale=f"Assignment for {unknown_id}",
            )
            session.add(assignment)

    # Test: Compute outcome
    outcome = _compute_outcome(run_id, config)

    assert isinstance(outcome, OutcomeSuccess)
    assert outcome.total_unknowns == 2
    assert outcome.clusters_created == 1
    assert outcome.mapped_to_existing == 0

    # Verify run status was updated
    with get_session() as session:
        updated_run = session.get(ClusteringRun, run_id)
        assert updated_run is not None
        assert updated_run.status == "completed"
        assert updated_run.completed_at is not None

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_compute_outcome_incomplete(test_db):
    """Test _compute_outcome returns OutcomeIncomplete when unknowns remain."""
    config = test_db

    # Setup: Create partial clustering run
    with get_session() as session:
        snapshot = make_test_snapshot("test/outcome-incomplete", "jkl012")
        session.add(snapshot)
        session.flush()
        snapshot_slug = snapshot.slug

        run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critique (needed for grader_run FK)
        critique = make_test_critique(snapshot_slug)
        session.add(critique)
        session.flush()
        critique_id = critique.id

        # Create grader run with 3 unknowns
        grader_run = make_test_grader_run(
            snapshot_slug,
            critique_id,
            unknowns=[
                {"id": "unknown-x", "rationale": "Issue X"},
                {"id": "unknown-y", "rationale": "Issue Y"},
                {"id": "unknown-z", "rationale": "Issue Z"},
            ],
        )
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create cluster and assign only 1 unknown
        cluster = UnknownCluster(
            clustering_run_id=run_id, cluster_name="partial-cluster", description="Partial cluster"
        )
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id

        assignment = UnknownAssignment(
            clustering_run_id=run_id,
            grader_run_id=grader_run_id,
            unknown_id="unknown-x",
            cluster_id=cluster_id,
            rationale="Assignment for unknown-x",
        )
        session.add(assignment)

    # Test: Compute outcome (2 unknowns remaining)
    outcome = _compute_outcome(run_id, config)

    assert isinstance(outcome, OutcomeIncomplete)
    assert outcome.remaining_unknowns == 2
    assert "2 unknowns not assigned" in outcome.message

    # Verify run status was NOT updated to completed
    with get_session() as session:
        updated_run = session.get(ClusteringRun, run_id)
        assert updated_run is not None
        assert updated_run.status == "in_progress"
        assert updated_run.completed_at is None

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_compute_outcome_with_mapped_to_existing(test_db):
    """Test _compute_outcome counts mapped_to_existing correctly."""
    config = test_db

    # Setup: Create clustering run with mixed assignments
    with get_session() as session:
        snapshot = make_test_snapshot("test/outcome-mapped", "mno345")
        session.add(snapshot)
        session.flush()
        snapshot_slug = snapshot.slug

        run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critique (needed for grader_run FK)
        critique = make_test_critique(snapshot_slug)
        session.add(critique)
        session.flush()
        critique_id = critique.id

        # Create grader run with 4 unknowns
        grader_run = make_test_grader_run(
            snapshot_slug,
            critique_id,
            unknowns=[
                {"id": "unknown-1", "rationale": "Issue 1"},
                {"id": "unknown-2", "rationale": "Issue 2"},
                {"id": "unknown-3", "rationale": "Issue 3"},
                {"id": "unknown-4", "rationale": "Issue 4"},
            ],
        )
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create cluster
        cluster = UnknownCluster(clustering_run_id=run_id, cluster_name="new-cluster", description="New cluster")
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id

        # Assign 2 to new cluster, 1 to TP, 1 to FP
        session.add(
            UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id="unknown-1",
                cluster_id=cluster_id,
                rationale="New cluster",
            )
        )
        session.add(
            UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id="unknown-2",
                cluster_id=cluster_id,
                rationale="New cluster",
            )
        )
        session.add(
            UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id="unknown-3",
                mapped_tp_id="existing-tp-123",
                rationale="Maps to existing TP",
            )
        )
        session.add(
            UnknownAssignment(
                clustering_run_id=run_id,
                grader_run_id=grader_run_id,
                unknown_id="unknown-4",
                mapped_fp_id="existing-fp-456",
                rationale="Maps to existing FP",
            )
        )
    # Test: Compute outcome
    outcome = _compute_outcome(run_id, config)

    assert isinstance(outcome, OutcomeSuccess)
    assert outcome.total_unknowns == 4
    assert outcome.clusters_created == 1
    assert outcome.mapped_to_existing == 2  # 1 TP + 1 FP

    # No cleanup needed - test_db fixture drops entire database
