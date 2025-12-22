"""Integration test for clustering agent orchestration.

Tests the full orchestrator without running an actual LLM agent:
- Database setup (clustering run, snapshot, grader runs with unknowns)
- Completion detection handler
- Outcome computation
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from tests.props.conftest import (
    make_clustering_run,
    make_critic_run,
    make_grader_run,
    make_reported_issues,
    make_unknown_grading_decisions,
)

from adgn.agent.loop_control import Abort, NoAction
from adgn.props.clustering.cluster_agent import ClusteringHandler, OutcomeIncomplete, OutcomeSuccess, _compute_outcome
from adgn.props.db.clustering_models import UnknownAssignment, UnknownCluster
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun, AgentRunStatus


async def test_completion_handler_detects_all_assigned(synced_test_session: Session, test_db: DatabaseConfig):
    """Test ClusteringHandler detects when all unknowns are assigned."""
    # Setup: Use git fixture example, create clustering run, grader runs with unknowns
    example = synced_test_session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
    assert example is not None, "test-trivial example not found in git fixtures"
    snapshot_slug = example.snapshot_slug

    run = make_clustering_run(snapshot_slug)
    critic_run = make_critic_run(example=example)
    grader_run = make_grader_run(critic_run=critic_run)
    synced_test_session.add_all([run, critic_run, grader_run])

    # Create reported issues and mark them as unknowns via grading decisions
    unknown_ids = ["unknown-1", "unknown-2", "unknown-3"]
    make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=unknown_ids, session=synced_test_session)
    make_unknown_grading_decisions(
        agent_run_id=grader_run.agent_run_id, unknown_ids=unknown_ids, session=synced_test_session
    )

    # Create cluster and commit to make data visible to handler's own session
    cluster = UnknownCluster(agent_run_id=run.agent_run_id, cluster_name="test-cluster", description="Test cluster")
    synced_test_session.add(cluster)
    synced_test_session.commit()

    # Store IDs before handler call (handler uses its own session, may detach objects)
    run_id = run.agent_run_id
    grader_run_id = grader_run.agent_run_id
    cluster_id = cluster.id

    # Test: Handler should return NoAction when not all assigned
    handler = ClusteringHandler(run_id, snapshot_slug)
    decision = handler.on_before_sample()
    assert isinstance(decision, NoAction)

    # Assign 2 unknowns
    for unknown_id in ["unknown-1", "unknown-2"]:
        assignment = UnknownAssignment(
            agent_run_id=run_id,
            grader_run_id=grader_run_id,
            unknown_id=unknown_id,
            cluster_id=cluster_id,
            rationale=f"Test assignment for {unknown_id}",
        )
        synced_test_session.add(assignment)
    synced_test_session.commit()

    # Handler should still return NoAction (1 unknown remaining)
    decision = handler.on_before_sample()
    assert isinstance(decision, NoAction)

    # Assign the last unknown
    assignment = UnknownAssignment(
        agent_run_id=run_id,
        grader_run_id=grader_run_id,
        unknown_id="unknown-3",
        cluster_id=cluster_id,
        rationale="Test assignment for unknown-3",
    )
    synced_test_session.add(assignment)
    synced_test_session.commit()

    # Handler should now return Abort (all assigned)
    decision = handler.on_before_sample()
    assert isinstance(decision, Abort)


async def test_completion_handler_no_unknowns(synced_test_session: Session, test_db: DatabaseConfig):
    """Test ClusteringHandler aborts immediately when no unknowns exist."""
    # Setup: Use git fixture, create run with NO grader runs (no unknowns)
    example = synced_test_session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
    assert example is not None, "Test fixture example not found"
    snapshot_slug = example.snapshot_slug

    run = make_clustering_run(snapshot_slug)
    synced_test_session.add(run)
    synced_test_session.commit()

    # Test: Handler should return Abort immediately (no unknowns to cluster)
    handler = ClusteringHandler(run.agent_run_id, snapshot_slug)
    decision = handler.on_before_sample()
    assert isinstance(decision, Abort)


async def test_compute_outcome_success(synced_test_session: Session, test_db: DatabaseConfig):
    """Test _compute_outcome returns OutcomeSuccess when all unknowns assigned."""
    # Setup: Create complete clustering run
    example = synced_test_session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
    assert example is not None, "test-trivial example not found in git fixtures"
    snapshot_slug = example.snapshot_slug

    run = make_clustering_run(snapshot_slug)
    critic_run = make_critic_run(example=example)
    grader_run = make_grader_run(critic_run=critic_run)
    synced_test_session.add_all([run, critic_run, grader_run])

    # Create reported issues and mark them as unknowns via grading decisions
    unknown_ids = ["unknown-a", "unknown-b"]
    make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=unknown_ids, session=synced_test_session)
    make_unknown_grading_decisions(
        agent_run_id=grader_run.agent_run_id,
        unknown_ids=unknown_ids,
        session=synced_test_session,
        rationale_prefix="Unknown issue (no TP match)",
    )

    # Create cluster (flush to get auto-generated ID before creating assignments)
    cluster = UnknownCluster(agent_run_id=run.agent_run_id, cluster_name="test-cluster", description="Test cluster")
    synced_test_session.add(cluster)
    synced_test_session.flush()

    # Assign both unknowns to cluster
    for unknown_id in ["unknown-a", "unknown-b"]:
        assignment = UnknownAssignment(
            agent_run_id=run.agent_run_id,
            grader_run_id=grader_run.agent_run_id,
            unknown_id=unknown_id,
            cluster_id=cluster.id,
            rationale=f"Assignment for {unknown_id}",
        )
        synced_test_session.add(assignment)

    synced_test_session.commit()

    # Test: Compute outcome
    outcome = _compute_outcome(run.agent_run_id, snapshot_slug, test_db)

    assert isinstance(outcome, OutcomeSuccess)
    assert outcome.total_unknowns == 2
    assert outcome.clusters_created == 1
    assert outcome.mapped_to_existing == 0

    # Verify run status was updated
    synced_test_session.expire_all()
    updated_run = synced_test_session.get(AgentRun, run.agent_run_id)
    assert updated_run is not None
    assert updated_run.status == AgentRunStatus.COMPLETED


async def test_compute_outcome_incomplete(synced_test_session: Session, test_db: DatabaseConfig):
    """Test _compute_outcome returns OutcomeIncomplete when unknowns remain."""
    # Setup: Create partial clustering run
    example = synced_test_session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
    assert example is not None, "test-trivial example not found in git fixtures"
    snapshot_slug = example.snapshot_slug

    run = make_clustering_run(snapshot_slug)
    critic_run = make_critic_run(example=example)
    grader_run = make_grader_run(critic_run=critic_run)
    synced_test_session.add_all([run, critic_run, grader_run])

    # Create reported issues and mark them as unknowns via grading decisions
    unknown_ids = ["unknown-1", "unknown-2", "unknown-3"]
    make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=unknown_ids, session=synced_test_session)
    make_unknown_grading_decisions(
        agent_run_id=grader_run.agent_run_id, unknown_ids=unknown_ids, session=synced_test_session
    )

    # Create cluster and assign only 1 unknown (flush to get auto-generated ID)
    cluster = UnknownCluster(
        agent_run_id=run.agent_run_id, cluster_name="partial-cluster", description="Partial cluster"
    )
    synced_test_session.add(cluster)
    synced_test_session.flush()

    assignment = UnknownAssignment(
        agent_run_id=run.agent_run_id,
        grader_run_id=grader_run.agent_run_id,
        unknown_id="unknown-x",
        cluster_id=cluster.id,
        rationale="Assignment for unknown-x",
    )
    synced_test_session.add(assignment)
    synced_test_session.commit()

    # Test: Compute outcome (2 unknowns remaining)
    outcome = _compute_outcome(run.agent_run_id, snapshot_slug, test_db)

    assert isinstance(outcome, OutcomeIncomplete)
    assert outcome.remaining_unknowns == 2
    assert "2 unknowns not assigned" in outcome.message

    # Verify run status was NOT updated to completed
    synced_test_session.expire_all()
    updated_run = synced_test_session.get(AgentRun, run.agent_run_id)
    assert updated_run is not None
    assert updated_run.status == AgentRunStatus.IN_PROGRESS


async def test_compute_outcome_with_mapped_to_existing(synced_test_session: Session, test_db: DatabaseConfig):
    """Test _compute_outcome counts mapped_to_existing correctly."""
    # Setup: Create clustering run with mixed assignments
    example = synced_test_session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
    assert example is not None, "test-trivial example not found in git fixtures"
    snapshot_slug = example.snapshot_slug

    run = make_clustering_run(snapshot_slug)
    critic_run = make_critic_run(example=example)
    grader_run = make_grader_run(critic_run=critic_run)
    synced_test_session.add_all([run, critic_run, grader_run])

    # Create reported issues and mark them as unknowns via grading decisions
    unknown_ids = ["unknown-1", "unknown-2", "unknown-3", "unknown-4"]
    make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=unknown_ids, session=synced_test_session)
    make_unknown_grading_decisions(
        agent_run_id=grader_run.agent_run_id, unknown_ids=unknown_ids, session=synced_test_session
    )

    # Create cluster (flush to get auto-generated ID before creating assignments)
    cluster = UnknownCluster(agent_run_id=run.agent_run_id, cluster_name="new-cluster", description="New cluster")
    synced_test_session.add(cluster)
    synced_test_session.flush()

    # Assign 2 to new cluster, 1 to TP, 1 to FP
    synced_test_session.add(
        UnknownAssignment(
            agent_run_id=run.agent_run_id,
            grader_run_id=grader_run.agent_run_id,
            unknown_id="unknown-1",
            cluster_id=cluster.id,
            rationale="New cluster",
        )
    )
    synced_test_session.add(
        UnknownAssignment(
            agent_run_id=run.agent_run_id,
            grader_run_id=grader_run.agent_run_id,
            unknown_id="unknown-2",
            cluster_id=cluster.id,
            rationale="New cluster",
        )
    )
    synced_test_session.add(
        UnknownAssignment(
            agent_run_id=run.agent_run_id,
            grader_run_id=grader_run.agent_run_id,
            unknown_id="unknown-3",
            mapped_tp_id="existing-tp-123",
            rationale="Maps to existing TP",
        )
    )
    synced_test_session.add(
        UnknownAssignment(
            agent_run_id=run.agent_run_id,
            grader_run_id=grader_run.agent_run_id,
            unknown_id="unknown-4",
            mapped_fp_id="existing-fp-456",
            rationale="Maps to existing FP",
        )
    )

    synced_test_session.commit()

    # Test: Compute outcome
    outcome = _compute_outcome(run.agent_run_id, snapshot_slug, test_db)

    assert isinstance(outcome, OutcomeSuccess)
    assert outcome.total_unknowns == 4
    assert outcome.clusters_created == 1
    assert outcome.mapped_to_existing == 2  # 1 TP + 1 FP
