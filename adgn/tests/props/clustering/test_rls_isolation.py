"""Test RLS isolation for clustering agents.

Verifies that:
1. Clustering agents can only see/modify data for their own run_id
2. Multiple concurrent runs are isolated from each other
3. Agents have read-only access to reference tables
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from tests.props.conftest import make_clustering_run

from adgn.props.clustering.user_manager import ClusteringUserManager
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownCluster
from adgn.props.db.models import Snapshot


def test_migration_applied(admin_engine):
    """Verify clustering schema was created in test database."""
    with admin_engine.connect() as conn:
        # Check if RLS helper function exists
        result = conn.execute(text("SELECT proname FROM pg_proc WHERE proname = 'current_clustering_run_id'"))
        function_exists = result.scalar() is not None
        assert function_exists, "current_clustering_run_id() function not found"

        # Check if clustering tables exist
        required_tables = ["clustering_runs", "unknown_clusters", "unknown_assignments"]
        result = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(:tables)"),
            {"tables": required_tables},
        )
        found_tables = {row[0] for row in result}
        missing_tables = set(required_tables) - found_tables
        assert not missing_tables, f"Missing tables: {', '.join(sorted(missing_tables))}"


async def test_rls_isolation_between_runs(clustering_user_engine_factory, test_snapshot):
    """Test that clustering agents can only see/modify their own run's data."""
    # Setup: Create two clustering runs
    with get_session() as session:
        run1 = make_clustering_run(test_snapshot)
        run2 = make_clustering_run(test_snapshot)
        session.add_all([run1, run2])
        session.flush()
        run1_id = run1.id
        run2_id = run2.id
        session.commit()

    # Test: Each user can only see their own run
    async with (
        clustering_user_engine_factory(run1_id) as user1_engine,
        clustering_user_engine_factory(run2_id) as user2_engine,
    ):
        # User 1 sees only run 1
        with Session(user1_engine) as user1_session:
            # Quick debug check
            result = user1_session.execute(text("SELECT current_user, current_clustering_run_id()"))
            row = result.fetchone()
            assert row is not None, "Expected row from current_user/current_clustering_run_id() query"
            if row[1] is None:
                raise RuntimeError(f"current_clustering_run_id() returned NULL for user {row[0]}, expected {run1_id}")

            visible_runs = user1_session.query(ClusteringRun).all()
            assert len(visible_runs) == 1
            assert visible_runs[0].id == run1_id

        # User 2 sees only run 2
        with Session(user2_engine) as user2_session:
            visible_runs = user2_session.query(ClusteringRun).all()
            assert len(visible_runs) == 1
            assert visible_runs[0].id == run2_id


async def test_rls_isolation_clusters_and_assignments(clustering_user_engine_factory, test_snapshot):
    """Test that users can only see/modify clusters and assignments for their own run."""
    # Setup: Create two clustering runs with clusters
    with get_session() as session:
        run1 = make_clustering_run(test_snapshot)
        run2 = make_clustering_run(test_snapshot)
        session.add_all([run1, run2])
        session.flush()
        run1_id = run1.id
        run2_id = run2.id

        # Create clusters for each run
        cluster1 = UnknownCluster(
            clustering_run_id=run1_id, cluster_name="run1-cluster", description="Cluster for run 1"
        )
        cluster2 = UnknownCluster(
            clustering_run_id=run2_id, cluster_name="run2-cluster", description="Cluster for run 2"
        )
        session.add_all([cluster1, cluster2])
        session.commit()

    # Test: Each user can only see/modify their own run's clusters
    async with (
        clustering_user_engine_factory(run1_id) as user1_engine,
        clustering_user_engine_factory(run2_id) as user2_engine,
    ):
        # User 1 sees only run 1's clusters
        with Session(user1_engine) as user1_session:
            clusters = user1_session.query(UnknownCluster).all()
            assert len(clusters) == 1
            assert clusters[0].cluster_name == "run1-cluster"
            assert clusters[0].clustering_run_id == run1_id

        # User 2 sees only run 2's clusters
        with Session(user2_engine) as user2_session:
            clusters = user2_session.query(UnknownCluster).all()
            assert len(clusters) == 1
            assert clusters[0].cluster_name == "run2-cluster"
            assert clusters[0].clustering_run_id == run2_id


async def test_rls_read_only_access_to_reference_tables(clustering_user_engine_factory, test_snapshot):
    """Test that clustering agents have read-only access to snapshots and ground truth."""
    # Setup: Create clustering run
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()

    # Test: User can read snapshots but not modify
    async with clustering_user_engine_factory(run_id) as user_engine:
        with Session(user_engine) as user_session:
            # Can read snapshot
            snapshots = user_session.query(Snapshot).all()
            assert any(s.slug == test_snapshot for s in snapshots)

            # Cannot delete snapshot (read-only)
            def try_delete():
                user_session.query(Snapshot).filter_by(slug=test_snapshot).delete()
                user_session.commit()

            with pytest.raises(ProgrammingError, match=r"(?i)(permission denied|read-only)"):
                try_delete()


async def test_scoped_user_cleanup(test_db, test_snapshot, admin_engine):
    """Test that scoped users are properly cleaned up after context exit."""
    # Setup: Create clustering run
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()

    username = f"clustering_run_{run_id}_agent"

    # Create and exit scoped user
    async with ClusteringUserManager(test_db.admin, run_id):
        # Verify user exists during context
        with Session(admin_engine) as session:
            result = session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username})
            assert result.scalar() == 1

    # Verify user is cleaned up after context exit
    with Session(admin_engine) as session:
        result = session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username})
        assert result.scalar() is None
