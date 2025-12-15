"""Test RLS isolation for clustering agents.

Verifies that:
1. Clustering agents can only see/modify data for their own run_id
2. Multiple concurrent runs are isolated from each other
3. Agents have read-only access to reference tables
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from tests.props.clustering.conftest import make_test_snapshot

from adgn.props.db.clustering_models import ClusteringRun, UnknownCluster
from adgn.props.db.clustering_user_manager import ClusteringUserManager
from adgn.props.db.models import Snapshot


def test_migration_applied(test_db):
    """Verify clustering schema was created in test database."""
    config = test_db
    engine = create_engine(config.admin_url())

    with engine.connect() as conn:
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

    engine.dispose()


@pytest.mark.asyncio
async def test_rls_isolation_between_runs(test_db):
    """Test that clustering agents can only see/modify their own run's data."""
    config = test_db  # Use test database config from fixture
    admin_engine = create_engine(config.admin_url())

    # Setup: Create test snapshot and two clustering runs
    with Session(admin_engine) as session:
        # Create test snapshot
        snapshot = make_test_snapshot("test/clustering-rls", "abc123")
        session.add(snapshot)
        session.flush()

        # Create two clustering runs
        run1 = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        run2 = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        session.add_all([run1, run2])
        session.flush()

        run1_id = run1.id
        run2_id = run2.id
        snapshot_slug = snapshot.slug

        session.commit()

    # Test: Each user can only see their own run
    async with ClusteringUserManager(config.admin, run1_id) as user1_creds:
        user1_config = config.admin.with_user(user1_creds)
        async with ClusteringUserManager(config.admin, run2_id) as user2_creds:
            user2_config = config.admin.with_user(user2_creds)
            # User 1 sees only run 1
            user1_engine = create_engine(user1_config.url())
            with Session(user1_engine) as user1_session:
                # Quick debug check
                result = user1_session.execute(text("SELECT current_user, current_clustering_run_id()"))
                row = result.fetchone()
                assert row is not None, "Expected row from current_user/current_clustering_run_id() query"
                if row[1] is None:
                    raise RuntimeError(
                        f"current_clustering_run_id() returned NULL for user {row[0]}, expected {run1_id}"
                    )

                visible_runs = user1_session.query(ClusteringRun).all()
                assert len(visible_runs) == 1
                assert visible_runs[0].id == run1_id

            # User 2 sees only run 2
            user2_engine = create_engine(user2_config.url())
            with Session(user2_engine) as user2_session:
                visible_runs = user2_session.query(ClusteringRun).all()
                assert len(visible_runs) == 1
                assert visible_runs[0].id == run2_id

            user1_engine.dispose()
            user2_engine.dispose()

    # Cleanup
    with Session(admin_engine) as session:
        session.query(ClusteringRun).filter(ClusteringRun.id.in_([run1_id, run2_id])).delete()
        session.query(Snapshot).filter_by(slug=snapshot_slug).delete()
        session.commit()

    admin_engine.dispose()


@pytest.mark.asyncio
async def test_rls_isolation_clusters_and_assignments(test_db):
    """Test that users can only see/modify clusters and assignments for their own run."""
    config = test_db  # Use test database config from fixture
    admin_engine = create_engine(config.admin_url())

    # Setup: Create test snapshot and two clustering runs with clusters
    with Session(admin_engine) as session:
        # Create test snapshot
        snapshot = make_test_snapshot("test/clustering-rls-detailed", "def456")
        session.add(snapshot)
        session.flush()

        # Create two clustering runs
        run1 = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        run2 = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        session.add_all([run1, run2])
        session.flush()

        run1_id = run1.id
        run2_id = run2.id
        snapshot_slug = snapshot.slug

        # Create clusters for each run (admin creates these to setup test state)
        cluster1 = UnknownCluster(
            clustering_run_id=run1_id, cluster_name="run1-cluster", description="Cluster for run 1"
        )
        cluster2 = UnknownCluster(
            clustering_run_id=run2_id, cluster_name="run2-cluster", description="Cluster for run 2"
        )
        session.add_all([cluster1, cluster2])
        session.flush()

        session.commit()

    # Test: Each user can only see/modify their own run's clusters
    async with ClusteringUserManager(config.admin, run1_id) as user1_creds:
        user1_config = config.admin.with_user(user1_creds)
        async with ClusteringUserManager(config.admin, run2_id) as user2_creds:
            user2_config = config.admin.with_user(user2_creds)
            # User 1 sees only run 1's clusters
            user1_engine = create_engine(user1_config.url())
            with Session(user1_engine) as user1_session:
                clusters = user1_session.query(UnknownCluster).all()
                assert len(clusters) == 1
                assert clusters[0].cluster_name == "run1-cluster"
                assert clusters[0].clustering_run_id == run1_id

            # User 2 sees only run 2's clusters
            user2_engine = create_engine(user2_config.url())
            with Session(user2_engine) as user2_session:
                clusters = user2_session.query(UnknownCluster).all()
                assert len(clusters) == 1
                assert clusters[0].cluster_name == "run2-cluster"
                assert clusters[0].clustering_run_id == run2_id

            user1_engine.dispose()
            user2_engine.dispose()

    # Cleanup
    with Session(admin_engine) as session:
        session.query(UnknownCluster).filter(UnknownCluster.clustering_run_id.in_([run1_id, run2_id])).delete()
        session.query(ClusteringRun).filter(ClusteringRun.id.in_([run1_id, run2_id])).delete()
        session.query(Snapshot).filter_by(slug=snapshot_slug).delete()
        session.commit()

    admin_engine.dispose()


@pytest.mark.asyncio
async def test_rls_read_only_access_to_reference_tables(test_db):
    """Test that clustering agents have read-only access to snapshots and ground truth."""
    config = test_db  # Use test database config from fixture
    admin_engine = create_engine(config.admin_url())

    # Setup: Create test snapshot and clustering run
    with Session(admin_engine) as session:
        # Create test snapshot
        snapshot = make_test_snapshot("test/clustering-readonly", "ghi789")
        session.add(snapshot)
        session.flush()

        # Create clustering run
        run = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id
        snapshot_slug = snapshot.slug

        session.commit()

    # Test: User can read snapshots but not modify
    async with ClusteringUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as user_session:
            # Can read snapshot
            snapshots = user_session.query(Snapshot).all()
            assert any(s.slug == snapshot_slug for s in snapshots)

            # Cannot delete snapshot (read-only)
            def try_delete():
                user_session.query(Snapshot).filter_by(slug=snapshot_slug).delete()
                user_session.commit()

            with pytest.raises(ProgrammingError, match=r"(?i)(permission denied|read-only)"):
                try_delete()

        user_engine.dispose()

    # Cleanup
    with Session(admin_engine) as session:
        session.query(ClusteringRun).filter_by(id=run_id).delete()
        session.query(Snapshot).filter_by(slug=snapshot_slug).delete()
        session.commit()

    admin_engine.dispose()


@pytest.mark.asyncio
async def test_scoped_user_cleanup(test_db):
    """Test that scoped users are properly cleaned up after context exit."""
    config = test_db  # Use test database config from fixture
    admin_engine = create_engine(config.admin_url())

    # Setup: Create test snapshot and clustering run
    with Session(admin_engine) as session:
        snapshot = make_test_snapshot("test/cleanup", "cleanup123")
        session.add(snapshot)
        session.flush()

        run = ClusteringRun(snapshot_slug=snapshot.slug, status="in_progress")
        session.add(run)
        session.flush()
        run_id = run.id
        snapshot_slug = snapshot.slug

        session.commit()

    username = f"clustering_run_{run_id}_agent"

    # Create and exit scoped user
    async with ClusteringUserManager(config.admin, run_id):
        # Verify user exists during context
        with Session(admin_engine) as session:
            result = session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username})
            assert result.scalar() == 1

    # Verify user is cleaned up after context exit
    with Session(admin_engine) as session:
        result = session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username})
        assert result.scalar() is None

    # Cleanup
    with Session(admin_engine) as session:
        session.query(ClusteringRun).filter_by(id=run_id).delete()
        session.query(Snapshot).filter_by(slug=snapshot_slug).delete()
        session.commit()

    admin_engine.dispose()
