"""Test bootstrap materials for clustering agent.

Validates that:
1. schema_docs.md exists and is readable
2. example_queries.py can extract run_id from username
3. Example queries work with RLS-scoped user
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from tests.props.conftest import make_clustering_run

from adgn.props.clustering.example_queries import get_current_run_id, list_clusters
from adgn.props.clustering.user_manager import ClusteringUserManager
from adgn.props.db import get_session
from adgn.props.db.clustering_models import UnknownCluster


def test_schema_docs_exists():
    """Verify schema_docs.md exists and is readable."""
    docs_path = Path(__file__).parent.parent.parent.parent / "src" / "adgn" / "props" / "clustering" / "schema_docs.md"
    assert docs_path.exists(), f"schema_docs.md not found at {docs_path}"

    content = docs_path.read_text()
    assert len(content) > 1000, "schema_docs.md seems too short"

    # Check for key sections
    assert "clustering_runs" in content
    assert "unknown_clusters" in content
    assert "unknown_assignments" in content
    assert "RLS" in content or "Row-Level Security" in content
    assert "current_clustering_run_id()" in content


def test_example_queries_exists():
    """Verify example_queries.py exists and is executable."""
    script_path = (
        Path(__file__).parent.parent.parent.parent / "src" / "adgn" / "props" / "clustering" / "example_queries.py"
    )
    assert script_path.exists(), f"example_queries.py not found at {script_path}"

    # Check it's a Python script with proper shebang
    first_line = script_path.read_text().split("\n")[0]
    assert first_line.startswith("#!"), "example_queries.py missing shebang"
    assert "python" in first_line.lower(), "shebang should reference python"


async def test_run_id_extraction(clustering_user_engine_factory, test_snapshot):
    """Test that current_clustering_run_id() correctly extracts run_id from username."""
    # Setup: Create clustering run
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()

    # Test: Verify run_id extraction works
    async with clustering_user_engine_factory(run_id) as user_engine:
        with Session(user_engine) as user_session:
            # Call the SQL function directly
            result = user_session.execute(text("SELECT current_clustering_run_id()"))
            extracted_run_id = result.scalar()

            assert extracted_run_id == run_id, f"Expected {run_id}, got {extracted_run_id}"

            # Verify username format
            result = user_session.execute(text("SELECT current_user"))
            username = result.scalar()
            expected_username = f"clustering_run_{run_id}_agent"
            assert username == expected_username, f"Expected {expected_username}, got {username}"


async def test_example_query_list_clusters(test_db, test_snapshot):
    """Test that example query functions work with RLS-scoped user."""
    # Setup: Create run and cluster
    with get_session() as session:
        run = make_clustering_run(test_snapshot)
        session.add(run)
        session.flush()
        run_id = run.id

        # Create a cluster
        cluster = UnknownCluster(
            clustering_run_id=run_id, cluster_name="test-cluster", description="Test cluster for bootstrap validation"
        )
        session.add(cluster)
        session.commit()

    # Test: Use example query function as clustering user
    async with ClusteringUserManager(test_db.admin, run_id) as creds:
        user_config = test_db.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as user_session:
            # Verify run_id extraction works
            detected_run_id = get_current_run_id(user_session)
            assert detected_run_id == run_id, f"get_current_run_id() returned {detected_run_id}, expected {run_id}"

            # Verify list_clusters works (captures stdout would be better, but this validates execution)
            try:
                list_clusters(user_session)
                # If it doesn't raise, the query worked
            except Exception as e:
                pytest.fail(f"list_clusters() raised: {e}")

        user_engine.dispose()
