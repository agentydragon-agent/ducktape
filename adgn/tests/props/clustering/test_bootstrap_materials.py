"""Test bootstrap materials for clustering agent.

Validates that:
1. current_agent_run_id() correctly extracts run_id from username
2. Example queries work with RLS-scoped user
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from tests.props.conftest import make_clustering_run

from adgn.props.agent_defs.clustering.examples.example_queries import get_current_agent_run_id, list_clusters
from adgn.props.db import get_session
from adgn.props.db.clustering_models import UnknownCluster
from adgn.props.db.temp_user_manager import TempUserManager


async def test_run_id_extraction(clustering_user_engine_factory, test_snapshot):
    """Test that current_agent_run_id() correctly extracts run_id from username."""
    # Setup: Create clustering run
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.agent_run_id
        session.commit()

    # Test: Verify run_id extraction works
    async with clustering_user_engine_factory(run_id) as user_engine:
        with Session(user_engine) as user_session:
            # Call the SQL function directly (unified function for all agent types)
            result = user_session.execute(text("SELECT current_agent_run_id()"))
            extracted_run_id = result.scalar()

            assert extracted_run_id == run_id, f"Expected {run_id}, got {extracted_run_id}"

            # Verify username format (unified agent_{uuid} pattern)
            result = user_session.execute(text("SELECT current_user"))
            username = result.scalar()
            expected_username = f"agent_{run_id}"
            assert username == expected_username, f"Expected {expected_username}, got {username}"


async def test_example_query_list_clusters(test_db, test_snapshot):
    """Test that example query functions work with RLS-scoped user."""
    # Setup: Create run and cluster
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.agent_run_id

        # Create a cluster
        cluster = UnknownCluster(
            agent_run_id=run_id, cluster_name="test-cluster", description="Test cluster for bootstrap validation"
        )
        session.add(cluster)
        session.commit()

    # Test: Use example query function as clustering user
    async with TempUserManager(test_db.admin, run_id) as creds:
        user_config = test_db.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as user_session:
            # Verify run_id extraction works
            detected_run_id = get_current_agent_run_id(user_session)
            assert detected_run_id == run_id, (
                f"get_current_agent_run_id() returned {detected_run_id}, expected {run_id}"
            )

            # Verify list_clusters works (captures stdout would be better, but this validates execution)
            try:
                list_clusters(user_session)
                # If it doesn't raise, the query worked
            except Exception as e:
                pytest.fail(f"list_clusters() raised: {e}")

        user_engine.dispose()
