"""Integration tests for PostgreSQL database access.

These tests use the TEST database (eval_results_test) and require:
- postgres container running (docker-compose up -d)
- init_db.sh run to create test database
- PROPS_TEST_DB_URL set (admin_user credentials for eval_results_test)
- PROPS_TEST_AGENT_DB_URL set (agent_user credentials for eval_results_test)

The test database is SEPARATE from production (eval_results).
Tests can freely drop/recreate tables without affecting production data.

Note: These tests share a module-scoped fixture and work correctly with pytest-xdist
because the project uses --dist=loadscope by default, which ensures all tests in
this module run in the same worker process.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from adgn.props.db import get_session, init_db, query_builders as qb
from adgn.props.db.models import CriticRun, Critique, GraderRun, Snapshot
from adgn.props.ids import SnapshotSlug

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]

# Test-specific SQL queries for RLS validation (should be blocked by agent_user)
SQL_BLOCKED_VALID_CRITIQUES = """
SELECT id, payload FROM critiques WHERE snapshot_slug LIKE 'valid/%' LIMIT 1;
"""

SQL_BLOCKED_VALID_GRADER_RUNS = """
SELECT id, snapshot_slug FROM grader_runs WHERE snapshot_slug LIKE 'valid/%' LIMIT 1;
"""

SQL_BLOCKED_VALID_EVENTS = """
SELECT e.transcript_id, e.event_type
FROM events e
JOIN critic_runs cr ON e.transcript_id = cr.transcript_id
WHERE cr.snapshot_slug LIKE 'valid/%'
LIMIT 1;
"""


# NOTE: DB write tests for critic/grader runs were removed during refactoring.
# The DB write logic is now tested as part of the full integration tests in
# test_prompt_optimizer_integration.py (test_critic_run_writes_to_database,
# test_grader_run_writes_to_database, test_events_are_written_to_database).


def test_rls_blocks_test_split_for_agent_user(test_db):
    """Test that agent_user cannot see test split data (RLS policy).

    Setup (as admin_user):
    - Create test specimen
    - Create critic run for test specimen

    Verify (as agent_user):
    - Cannot query critic runs for test split specimens
    """
    admin_url = os.environ.get("PROPS_TEST_DB_URL")
    agent_url = os.environ.get("PROPS_TEST_AGENT_DB_URL")
    if not agent_url:
        pytest.skip("PROPS_TEST_AGENT_DB_URL not set (agent_user credentials required)")

    # Setup: Use admin_user to write test data
    init_db(admin_url)
    with get_session() as session:
        test_specimen = Snapshot(slug="crush/test-specimen", split="test")
        session.merge(test_specimen)
        session.commit()

        # Create a critic run for the test specimen
        test_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256="a" * 64,
            snapshot_slug="crush/test-specimen",
            model="test-model",
            files=["test.py"],
            output={"tag": "failure", "error": "test"},
        )
        session.add(test_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS blocks test split
    init_db(agent_url)
    with get_session() as session:
        test_runs = (
            session.query(CriticRun)
            .filter(
                CriticRun.snapshot_slug == "crush/test-specimen"  # Test split
            )
            .all()
        )

        assert len(test_runs) == 0, "agent_user should not see test split data via RLS"


def test_rls_allows_train_split_for_agent_user(test_db):
    """Test that agent_user can see train split data (RLS policy allows).

    Setup (as admin_user):
    - Create train specimen
    - Create critic run for train specimen

    Verify (as agent_user):
    - Can query critic runs for train split specimens
    """
    admin_url = os.environ.get("PROPS_TEST_DB_URL")
    agent_url = os.environ.get("PROPS_TEST_AGENT_DB_URL")
    if not agent_url:
        pytest.skip("PROPS_TEST_AGENT_DB_URL not set")

    # Setup: Use admin_user to write test data
    init_db(admin_url)
    train_run_id = uuid4()
    with get_session() as session:
        train_specimen = Snapshot(slug="ducktape/2025-11-26-00", split="train")
        session.merge(train_specimen)
        session.commit()

        # Create a critic run for the train specimen
        train_run = CriticRun(
            transcript_id=train_run_id,
            prompt_sha256="b" * 64,
            snapshot_slug="ducktape/2025-11-26-00",
            model="test-model",
            files=["test.py"],
            output={"tag": "failure", "error": "test"},
        )
        session.add(train_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS allows train split
    init_db(agent_url)
    with get_session() as session:
        train_runs = session.query(CriticRun).filter(CriticRun.transcript_id == train_run_id).all()

        assert len(train_runs) == 1, "agent_user should see train split data via RLS"
        assert train_runs[0].snapshot_slug == "ducktape/2025-11-26-00"


def test_rls_blocks_valid_critique_details_for_agent_user(test_db):
    """Test that agent_user CANNOT see valid split critique details (RLS policy blocks).

    Setup (as admin_user):
    - Create valid specimen
    - Create critique for valid specimen
    - Create critic run for valid specimen

    Verify (as agent_user):
    - CANNOT query critiques for valid specimens (returns 0 rows)
    - CANNOT query critic_runs for valid specimens (returns 0 rows)
    - CAN query grader_runs for valid specimens (aggregate access allowed)
    """
    admin_url = os.environ.get("PROPS_TEST_DB_URL")
    agent_url = os.environ.get("PROPS_TEST_AGENT_DB_URL")
    if not agent_url:
        pytest.skip("PROPS_TEST_AGENT_DB_URL not set")

    # Setup: Use admin_user to write test data
    init_db(admin_url)
    valid_critique_id = uuid4()
    valid_run_id = uuid4()
    with get_session() as session:
        valid_specimen = Snapshot(slug="valid/spec-test", split="valid")
        session.merge(valid_specimen)
        session.commit()

        # Create a critique for the valid specimen
        valid_critique = Critique(
            id=valid_critique_id,
            snapshot_slug="valid/spec-test",
            payload={"issues": [{"id": "issue-1", "rationale": "Secret valid rationale"}], "notes_md": ""},
        )
        session.add(valid_critique)
        session.commit()

        # Create a critic run for the valid specimen
        valid_critic_run = CriticRun(
            transcript_id=valid_run_id,
            prompt_sha256="c" * 64,
            snapshot_slug="valid/spec-test",
            model="test-model",
            critique_id=valid_critique_id,
            files=["test.py"],
            output={"tag": "success"},
        )
        session.add(valid_critic_run)
        session.commit()

        # Create a grader run for the valid specimen (to test grader access works)
        valid_grader_run = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug="valid/spec-test",
            model="test-model",
            critique_id=valid_critique_id,
            output={
                "grade": {
                    "recall": 0.8,
                    "precision": 0.9,
                    "metrics": {"true_positives": 4, "false_positives": 1, "false_negatives": 1},
                }
            },
        )
        session.add(valid_grader_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS blocks valid detail access
    init_db(agent_url)
    with get_session() as session:
        # Should NOT see critique details for valid specimen
        valid_critiques = session.query(Critique).filter(Critique.snapshot_slug == "valid/spec-test").all()
        assert len(valid_critiques) == 0, "agent_user should NOT see valid split critiques via RLS"

        # Should NOT see critic_runs for valid specimen
        valid_critic_runs = session.query(CriticRun).filter(CriticRun.snapshot_slug == "valid/spec-test").all()
        assert len(valid_critic_runs) == 0, "agent_user should NOT see valid split critic_runs via RLS"

        # Should NOT see grader_runs directly for valid specimen (must use view instead)
        valid_grader_runs = session.query(GraderRun).filter(GraderRun.snapshot_slug == "valid/spec-test").all()
        assert len(valid_grader_runs) == 0, "agent_user should NOT see valid split grader_runs directly via RLS"

        # SHOULD see valid aggregates via the view
        result = session.execute(
            text("SELECT specimen, recall, precision FROM valid_grader_metrics WHERE specimen = 'valid/spec-test'")
        ).fetchall()
        assert len(result) == 1, "agent_user SHOULD see valid split aggregates via valid_grader_metrics view"
        assert result[0].recall == 0.8
        assert result[0].precision == 0.9

        # Test the blocked SQL from prompt: attempt to get critique details
        result = session.execute(text(SQL_BLOCKED_VALID_CRITIQUES)).fetchall()
        assert len(result) == 0, "Query for valid critiques should return 0 rows (RLS blocks)"

        # Test the blocked SQL from prompt: attempt to query grader_runs directly for valid
        result = session.execute(text(SQL_BLOCKED_VALID_GRADER_RUNS)).fetchall()
        assert len(result) == 0, "Query for valid grader_runs should return 0 rows (RLS blocks)"

        # Test the blocked SQL from prompt: attempt to trace back to prompt
        # Use query builder with valid/spec-test specimen
        result = session.execute(qb.link_grader_to_prompt(SnapshotSlug("valid/spec-test"), limit=1)).fetchall()
        assert len(result) == 0, (
            "Query tracing valid specimen to prompt should return 0 rows (RLS blocks critic_runs join)"
        )

        # Test the blocked SQL from prompt: attempt to get execution events
        result = session.execute(text(SQL_BLOCKED_VALID_EVENTS)).fetchall()
        assert len(result) == 0, "Query for valid execution events should return 0 rows (RLS blocks)"
