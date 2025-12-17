"""Integration test for clustering agent orchestration.

Tests the full orchestrator without running an actual LLM agent:
- Database setup (clustering run, snapshot, grader runs with unknowns)
- Completion detection handler
- Outcome computation
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from tests.props.conftest import make_clustering_run, make_critic_run, make_grader_run

from adgn.agent.loop_control import Abort, NoAction
from adgn.props.clustering.cluster_agent import (
    ClusteringCompletionHandler,
    OutcomeIncomplete,
    OutcomeSuccess,
    _compute_outcome,
)
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.examples import Example
from adgn.props.db.prompts import hash_and_upsert_prompt


@pytest.mark.asyncio
async def test_completion_handler_detects_all_assigned(synced_test_fixtures, test_db):
    """Test ClusteringCompletionHandler detects when all unknowns are assigned."""

    # Setup: Use git fixture example, create clustering run, grader runs with unknowns
    test_prompt_sha = hash_and_upsert_prompt("test prompt for clustering")

    with get_session() as session:
        # Query example from git fixtures
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "test-trivial example not found in git fixtures"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critic run (needed for grader_run FK)
        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.flush()

        # Create grader run with 3 unknowns
        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create cluster
        cluster = UnknownCluster(clustering_run_id=run_id, cluster_name="test-cluster", description="Test cluster")
        session.add(cluster)
        session.flush()

    # Test: Handler should return NoAction when not all assigned
    handler = ClusteringCompletionHandler(run_id, test_db)
    decision = handler.on_before_sample()
    assert isinstance(decision, NoAction)

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
    assert isinstance(decision, NoAction)

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
    assert isinstance(decision, Abort)

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_completion_handler_no_unknowns(synced_test_fixtures, test_db):
    """Test ClusteringCompletionHandler aborts immediately when no unknowns exist."""

    # Setup: Use git fixture, create run with NO grader runs (no unknowns)
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "Test fixture example not found"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.id

    # Test: Handler should return Abort immediately (no unknowns to cluster)
    handler = ClusteringCompletionHandler(run_id, test_db)
    decision = handler.on_before_sample()
    assert isinstance(decision, Abort)

    # No cleanup needed - test_db fixture drops entire database


@pytest.mark.asyncio
async def test_compute_outcome_success(synced_test_fixtures, test_db):
    """Test _compute_outcome returns OutcomeSuccess when all unknowns assigned."""

    # Setup: Create complete clustering run
    test_prompt_sha = hash_and_upsert_prompt("test prompt for clustering")

    with get_session() as session:
        # Query example from git fixtures
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "test-trivial example not found in git fixtures"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critic run (needed for grader_run FK)
        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.flush()

        # Create grader run with 2 unknowns
        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.id

        # Create unknown grading decisions (no TP match)
        from adgn.props.db.models import GradingDecision

        for unknown_id in ["unknown-a", "unknown-b"]:
            decision = GradingDecision(
                grader_run_id=grader_run_id,
                input_issue_id=unknown_id,
                target_tp_id=None,
                target_tp_occurrence_id=None,
                target_fp_id=None,
                target_fp_occurrence_id=None,
                credit=0.0,
                rationale="Unknown issue (no TP match)",
            )
            session.add(decision)

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
    outcome = _compute_outcome(run_id, test_db)

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
async def test_compute_outcome_incomplete(synced_test_fixtures, test_db):
    """Test _compute_outcome returns OutcomeIncomplete when unknowns remain."""

    # Setup: Create partial clustering run
    test_prompt_sha = hash_and_upsert_prompt("test prompt for clustering")

    with get_session() as session:
        # Query example from git fixtures
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "test-trivial example not found in git fixtures"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critic run (needed for grader_run FK)
        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.flush()

        # Create grader run with 3 unknowns
        grader_run = make_grader_run(critic_run=critic_run)
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
    outcome = _compute_outcome(run_id, test_db)

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
async def test_compute_outcome_with_mapped_to_existing(synced_test_fixtures, test_db):
    """Test _compute_outcome counts mapped_to_existing correctly."""

    # Setup: Create clustering run with mixed assignments
    test_prompt_sha = hash_and_upsert_prompt("test prompt for clustering")

    with get_session() as session:
        # Query example from git fixtures
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "test-trivial example not found in git fixtures"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.id

        # Create critic run (needed for grader_run FK)
        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.flush()

        # Create grader run with 4 unknowns
        grader_run = make_grader_run(critic_run=critic_run)
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
    outcome = _compute_outcome(run_id, test_db)

    assert isinstance(outcome, OutcomeSuccess)
    assert outcome.total_unknowns == 4
    assert outcome.clusters_created == 1
    assert outcome.mapped_to_existing == 2  # 1 TP + 1 FP

    # No cleanup needed - test_db fixture drops entire database
