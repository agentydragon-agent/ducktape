"""Integration tests for PostgreSQL database access.

These tests use per-test isolated databases and require:
- postgres container running (managed by devenv)
- PROPS_DB_* environment variables set (admin and agent credentials)

Each test gets its own database (created and destroyed by test_db fixture).
The test_db fixture returns a DatabaseConfig with both admin and agent credentials.

For RLS testing, tests use:
- admin_user (via get_session()) to write test data
- agent_user (via agent_session(test_db)) to verify read-only RLS policies

Note: These tests share a module-scoped fixture and work correctly with pytest-xdist
because the project uses --dist=loadscope by default, which ensures all tests in
this module run in the same worker process.
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import CriticRun, Critique, GraderRun, Snapshot
from adgn.props.ids import SnapshotSlug
from tests.props.conftest import TEST_FILES_HASH, TEST_FILES_LIST

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@contextmanager
def agent_session(config: DatabaseConfig):
    """Context manager for agent_user database session (for RLS testing).

    Args:
        config: Database configuration with agent credentials

    Yields:
        Session connected as agent_user (read-only with RLS)
    """
    engine = create_engine(config.agent_url(), echo=False)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


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


def test_rls_blocks_test_split_for_agent_user(test_db, test_prompt_sha):
    """Test that agent_user cannot see test split data (RLS policy).

    Setup (as admin_user):
    - Create test specimen
    - Create critic run for test specimen

    Verify (as agent_user):
    - Cannot query critic runs for test split specimens
    """
    # Setup: Use admin_user to write test data (already connected via test_db fixture)
    with get_session() as session:
        test_specimen = Snapshot(slug="crush/test-specimen", split="test")
        session.merge(test_specimen)
        session.commit()

        # Create a critic run for the test specimen
        test_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=test_prompt_sha,
            snapshot_slug="crush/test-specimen",
            model="test-model",
            files=TEST_FILES_LIST,
            files_hash=TEST_FILES_HASH,
            output={"tag": "failure", "error": "test"},
        )
        session.add(test_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS blocks test split
    with agent_session(test_db) as session:
        test_runs = (
            session.query(CriticRun)
            .filter(
                CriticRun.snapshot_slug == "crush/test-specimen"  # Test split
            )
            .all()
        )

        assert len(test_runs) == 0, "agent_user should not see test split data via RLS"


def test_rls_allows_train_split_for_agent_user(test_db, test_prompt_sha):
    """Test that agent_user can see train split data (RLS policy allows).

    Setup (as admin_user):
    - Create train specimen
    - Create critic run for train specimen

    Verify (as agent_user):
    - Can query critic runs for train split specimens
    """
    # Setup: Use admin_user to write test data (already connected via test_db fixture)
    train_run_id = uuid4()

    with get_session() as session:
        train_specimen = Snapshot(slug="ducktape/2025-11-26-00", split="train")
        session.merge(train_specimen)
        session.commit()

        # Create a critic run for the train specimen
        train_run = CriticRun(
            transcript_id=train_run_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug="ducktape/2025-11-26-00",
            model="test-model",
            files=TEST_FILES_LIST,
            files_hash=TEST_FILES_HASH,
            output={"tag": "failure", "error": "test"},
        )
        session.add(train_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS allows train split
    with agent_session(test_db) as session:
        train_runs = session.query(CriticRun).filter(CriticRun.transcript_id == train_run_id).all()

        assert len(train_runs) == 1, "agent_user should see train split data via RLS"
        assert train_runs[0].snapshot_slug == "ducktape/2025-11-26-00"


def test_rls_blocks_valid_critique_details_for_agent_user(test_db, test_prompt_sha):
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
    # Setup: Use admin_user to write test data (already connected via test_db fixture)
    valid_critique_id = uuid4()
    valid_run_id = uuid4()

    with get_session() as session:
        valid_specimen = Snapshot(slug="valid/spec-test", split="valid")
        session.merge(valid_specimen)
        session.commit()

        # Create TP records for valid/spec-test (required for snapshot_files_with_issues view)
        # TEST_FILES_LIST is ["test.py"]
        from pathlib import Path

        from adgn.props.db.models import TruePositive
        from adgn.props.models.true_positive import TruePositiveOccurrence

        tp = TruePositive(
            snapshot_slug="valid/spec-test",
            tp_id="test-tp-001",
            rationale="Test issue",
            occurrences=[
                TruePositiveOccurrence(files={Path("test.py"): None}, expect_caught_from={frozenset([Path("test.py")])})
            ],
        )
        session.add(tp)
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
            prompt_sha256=test_prompt_sha,
            snapshot_slug="valid/spec-test",
            model="test-model",
            critique_id=valid_critique_id,
            files=TEST_FILES_LIST,
            files_hash=TEST_FILES_HASH,
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
                    "canonical_tp_coverage": {},
                    "canonical_fp_coverage": {},
                    "novel_critique_issues": {},
                    "reported_issue_ratios": {"tp": 0.8, "fp": 0.1, "unlabeled": 0.1},
                    "recall": 0.8,
                    "summary": "Test grader run for RLS validation",
                }
            },
        )
        session.add(valid_grader_run)
        session.commit()

    # Verify: Connect as agent_user (read-only) and verify RLS blocks valid detail access
    with agent_session(test_db) as session:
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
            text(
                "SELECT snapshot_slug, recall FROM valid_full_snapshot_grader_metrics WHERE snapshot_slug = 'valid/spec-test'"
            )
        ).fetchall()
        assert len(result) == 1, (
            "agent_user SHOULD see valid split aggregates via valid_full_snapshot_grader_metrics view"
        )
        assert result[0].recall == 0.8

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
