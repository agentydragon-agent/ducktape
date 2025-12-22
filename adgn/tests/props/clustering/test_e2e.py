"""Test clustering agent with HTTP MCP mode (MCP-over-HTTP with bearer token auth).

Tests the HTTP transport for clustering agent using real Docker containers,
real PostgreSQL database, and mocked OpenAI responses.

All tests verify that bootstrap commands (including ./init) exit with code 0
before proceeding with the test scenario (via DockerExecCallWithBootstrapValidation).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from tests.props.conftest import (
    make_clustering_run,
    make_critic_run,
    make_grader_run,
    make_reported_issues,
    make_unknown_grading_decisions,
)
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation, Step

from adgn.props.clustering.cluster_agent import run_clustering_agent
from adgn.props.db import get_session
from adgn.props.db.clustering_models import UnknownAssignment, UnknownCluster
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun, AgentRunStatus
from adgn.props.ids import SnapshotSlug


def _setup_clustering_run_with_unknowns(synced_test_db) -> tuple[UUID, UUID, list[str]]:
    """Create a clustering run with grader run containing unknowns.

    Returns:
        tuple of (clustering_agent_run_id, grader_run_id, unknown_ids)
    """
    with get_session() as session:
        # Query example from git fixtures
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example is not None, "test-trivial example not found in git fixtures"
        snapshot_slug = example.snapshot_slug

        run = make_clustering_run(snapshot_slug)
        session.add(run)
        session.flush()
        run_id = run.agent_run_id

        # Create critic run (needed for grader_run FK)
        critic_run = make_critic_run(example=example)
        session.add(critic_run)
        session.flush()

        # Create grader run with unknowns
        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)
        session.flush()
        grader_run_id = grader_run.agent_run_id

        # Create reported issues and mark them as unknowns via grading decisions
        unknown_ids = ["unknown-1", "unknown-2"]
        make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=unknown_ids, session=session)
        make_unknown_grading_decisions(agent_run_id=grader_run.agent_run_id, unknown_ids=unknown_ids, session=session)
        session.commit()

        return run_id, grader_run_id, unknown_ids


def _make_clustering_steps(grader_run_id: UUID, unknown_ids: list[str]) -> list[Step]:
    """Create step sequence for clustering agent that creates a cluster and assigns unknowns.

    Uses bin CLI commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    First step validates bootstrap succeeded.
    """
    grader_run_str = str(grader_run_id)
    steps: list[Step] = [
        # 1. Create cluster via bin CLI - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "python",
                "/workspace/bin/clustering.py",
                "create-cluster",
                "dead-imports",
                "Unused imports that add no value",
            ],
            timeout_ms=15000,
        )
    ]

    # 2. Assign each unknown to the cluster
    for unknown_id in unknown_ids:
        steps.append(
            AssertDockerExecThenCall(
                expected_output="",  # Just check exit code 0
                next_cmd=[
                    "python",
                    "/workspace/bin/clustering.py",
                    "assign-to-cluster",
                    grader_run_str,
                    unknown_id,
                    "dead-imports",
                    f"Unused import in {unknown_id}",
                ],
                timeout_ms=15000,
            )
        )

    return steps


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_clustering_http_mode_assign_to_cluster(
    synced_test_db, make_step_runner, async_docker_client, test_specimens_hydrator
):
    """Test clustering agent assigns unknowns to a new cluster using CLI helpers.

    This tests the MCP-over-HTTP transport with:
    - Real Docker container executing CLI commands
    - Real PostgreSQL database with RLS-scoped temporary user
    - Mocked OpenAI responses
    """
    # Setup: Create clustering run with unknowns
    clustering_run_id, grader_run_id, unknown_ids = _setup_clustering_run_with_unknowns(synced_test_db)

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    steps = _make_clustering_steps(grader_run_id, unknown_ids)
    runner = make_step_runner(steps=steps)

    # Run clustering agent
    result = await run_clustering_agent(
        snapshot_slug=SnapshotSlug("test-fixtures/test-trivial"),
        hydrator=test_specimens_hydrator,
        docker_client=async_docker_client,
        db_config=synced_test_db,
        client=runner,
        agent_run_id=clustering_run_id,
    )

    # Verify result
    assert result is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, clustering_run_id)
        assert run is not None
        assert run.status == AgentRunStatus.COMPLETED

        # Check cluster was created
        clusters = session.query(UnknownCluster).filter_by(agent_run_id=clustering_run_id).all()
        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster.cluster_name == "dead-imports"

        # Check all unknowns were assigned
        assignments = session.query(UnknownAssignment).filter_by(agent_run_id=clustering_run_id).all()
        assert len(assignments) == len(unknown_ids)
        for assignment in assignments:
            assert assignment.cluster_id == cluster.id
            assert assignment.unknown_id in unknown_ids


def _make_clustering_steps_with_tp_mapping(grader_run_id: UUID, unknown_ids: list[str]) -> list[Step]:
    """Create step sequence for clustering agent that maps unknowns to existing TP/FP.

    Uses bin CLI commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    First step validates bootstrap succeeded.
    """
    grader_run_str = str(grader_run_id)
    return [
        # 1. Map first unknown to existing TP - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "python",
                "/workspace/bin/clustering.py",
                "assign-to-tp",
                grader_run_str,
                unknown_ids[0],
                "test-issue",
                "Same issue as existing TP test-issue",
            ],
            timeout_ms=15000,
        ),
        # 2. Map second unknown to existing FP
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=[
                "python",
                "/workspace/bin/clustering.py",
                "assign-to-fp",
                grader_run_str,
                unknown_ids[1],
                "acceptable-duplication",
                "Known acceptable pattern",
            ],
            timeout_ms=15000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_clustering_http_mode_assign_to_existing(
    synced_test_db, make_step_runner, async_docker_client, test_specimens_hydrator
):
    """Test clustering agent maps unknowns to existing TP/FP using CLI helpers.

    This tests mapping unknowns to existing canonical issues instead of creating
    new clusters.
    """
    # Setup: Create clustering run with unknowns
    clustering_run_id, grader_run_id, unknown_ids = _setup_clustering_run_with_unknowns(synced_test_db)

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    steps = _make_clustering_steps_with_tp_mapping(grader_run_id, unknown_ids)
    runner = make_step_runner(steps=steps)

    # Run clustering agent
    result = await run_clustering_agent(
        snapshot_slug=SnapshotSlug("test-fixtures/test-trivial"),
        hydrator=test_specimens_hydrator,
        docker_client=async_docker_client,
        db_config=synced_test_db,
        client=runner,
        agent_run_id=clustering_run_id,
    )

    # Verify result
    assert result is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, clustering_run_id)
        assert run is not None
        assert run.status == AgentRunStatus.COMPLETED

        # Check no new clusters were created
        clusters = session.query(UnknownCluster).filter_by(agent_run_id=clustering_run_id).all()
        assert len(clusters) == 0

        # Check all unknowns were assigned to existing TP/FP
        assignments = session.query(UnknownAssignment).filter_by(agent_run_id=clustering_run_id).all()
        assert len(assignments) == len(unknown_ids)

        # Verify mapping types
        tp_assignments = [a for a in assignments if a.mapped_tp_id is not None]
        fp_assignments = [a for a in assignments if a.mapped_fp_id is not None]
        assert len(tp_assignments) == 1
        assert len(fp_assignments) == 1
        assert tp_assignments[0].mapped_tp_id == "test-issue"
        assert fp_assignments[0].mapped_fp_id == "acceptable-duplication"
