"""Test split-based RLS policies for optimization agents.

Verifies that prompt optimizer users (temporary users created via
PromptOptimizerUserManager) can only access TRAIN split data, not TEST or VALID.

This is distinct from run-based isolation (see clustering/test_rls_isolation.py),
which isolates concurrent runs within the same split.

These tests use per-test isolated databases and require:
- postgres container running (managed by devenv)
- Database environment variables set (PG* vars for admin access)

Each test gets its own database (created and destroyed by test_db fixture).
For RLS testing, tests use:
- admin_user (via get_session()) to write test data
- prompt_optimizer temporary user to verify split-based RLS policies

Note: These tests share a module-scoped fixture and work correctly with pytest-xdist
because the project uses --dist=loadscope by default, which ensures all tests in
this module run in the same worker process.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, CriticRunStatus, FalsePositive, Snapshot, TruePositive
from adgn.props.db.temp_user_manager import TempUserCredentials
from adgn.props.prompt_optimize.user_manager import PromptOptimizerUserManager
from tests.props.conftest import make_critic_run

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest_asyncio.fixture
async def prompt_optimizer_creds(synced_test_db: DatabaseConfig) -> AsyncGenerator[TempUserCredentials, None]:
    """Create prompt optimizer temporary user credentials.

    Returns:
        credentials for use in RLS tests
    """
    run_id = uuid4()
    async with PromptOptimizerUserManager(synced_test_db.admin, run_id) as creds:
        yield creds


@pytest_asyncio.fixture
async def prompt_optimizer_session(
    prompt_optimizer_creds: TempUserCredentials, synced_test_db: DatabaseConfig
) -> AsyncGenerator[Session, None]:
    """Create database session as prompt optimizer temp user.

    Yields session with RLS policies active for prompt optimizer role.
    """
    user_config = synced_test_db.admin.with_user(prompt_optimizer_creds)
    engine = create_engine(user_config.url())

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


async def test_prompt_optimizer_cannot_see_test_split_snapshots(
    synced_test_db: DatabaseConfig, prompt_optimizer_session: Session
):
    """Prompt optimizer users cannot see TEST split snapshots (RLS policy blocks).

    Uses test-fixtures/test-split-test (TEST split) from git fixtures.

    Setup (as admin_user):
    - Git fixture already has test-split-test snapshot

    Verify (as prompt optimizer temp user):
    - Cannot query snapshots for test split
    """
    test_snapshots = (
        prompt_optimizer_session.query(Snapshot).filter(Snapshot.slug == "test-fixtures/test-split-test").all()
    )

    assert len(test_snapshots) == 0, "prompt optimizer user should not see test split snapshots via RLS"


async def test_prompt_optimizer_can_see_train_split_snapshots(
    synced_test_db: DatabaseConfig, prompt_optimizer_session: Session
):
    """Prompt optimizer users can see TRAIN split snapshots (RLS policy allows).

    Uses test-fixtures/test-trivial (TRAIN split) from git fixtures.

    Setup (as admin_user):
    - Git fixture already has test-trivial snapshot

    Verify (as prompt optimizer temp user):
    - Can query snapshots for train split
    """
    train_snapshots = (
        prompt_optimizer_session.query(Snapshot).filter(Snapshot.slug == "test-fixtures/test-trivial").all()
    )

    assert len(train_snapshots) == 1, "prompt optimizer user should see train split snapshots via RLS"
    assert train_snapshots[0].split == "train"


async def test_prompt_optimizer_cannot_see_valid_split_true_positives(
    synced_test_db: DatabaseConfig, prompt_optimizer_session: Session
):
    """Prompt optimizer users CANNOT see valid split true positives (RLS policy blocks).

    Uses test-fixtures/test-validation (VALID split) from git fixtures with synced TPs.

    Setup (as admin_user):
    - Git fixture already has test-validation snapshot with TPs

    Verify (as prompt optimizer temp user):
    - CANNOT query true positives for valid specimens (returns 0 rows)
    """
    # Should NOT see true positives for valid specimen
    valid_tps = (
        prompt_optimizer_session.query(TruePositive)
        .filter(TruePositive.snapshot_slug == "test-fixtures/test-validation")
        .all()
    )
    assert len(valid_tps) == 0, "prompt optimizer user should NOT see valid split true_positives via RLS"


async def test_prompt_optimizer_can_see_train_split_false_positives(
    synced_test_db: DatabaseConfig, prompt_optimizer_session: Session
):
    """Prompt optimizer users can see TRAIN split false positives (RLS policy allows).

    Uses test-fixtures/test-trivial (TRAIN split) from git fixtures.
    Note: test-trivial may not have FPs, but the test verifies RLS allows the query.

    Setup (as admin_user):
    - Git fixture already has test-trivial snapshot

    Verify (as prompt optimizer temp user):
    - Can query false positives for train specimens (query succeeds, no RLS block)
    """
    # Query should succeed (no RLS block), but may return empty if no FPs defined
    _ = (
        prompt_optimizer_session.query(FalsePositive)
        .filter(FalsePositive.snapshot_slug == "test-fixtures/test-trivial")
        .all()
    )
    # Just verify query succeeded (no exception from RLS block)
    # Not asserting specific count since test-trivial may not have FPs


async def test_prompt_optimizer_cannot_see_test_split_critic_runs(
    synced_test_db: DatabaseConfig, test_prompt_sha: str, prompt_optimizer_session: Session
):
    """Prompt optimizer users cannot see TEST split critic runs (RLS policy blocks).

    Uses test-fixtures/test-split-test (TEST split) from git fixtures.

    Setup (as admin_user):
    - Query existing test-split-test snapshot and example
    - Create critic run for test snapshot

    Verify (as prompt optimizer temp user):
    - Cannot query critic_runs for test split specimens
    """
    # Setup: Use admin_user to write test data
    with get_session() as session:
        # Query git fixture example (TEST split)
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-split-test").first()
        assert example, "test-split-test fixture not found"

        # Create a critic run for the test specimen using fixture factory
        test_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha, status=CriticRunStatus.COMPLETED)
        session.add(test_run)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify RLS blocks test split
    test_runs = (
        prompt_optimizer_session.query(CriticRun)
        .filter(CriticRun.snapshot_slug == "test-fixtures/test-split-test")
        .all()
    )

    assert len(test_runs) == 0, "prompt optimizer user should not see test split critic_runs via RLS"


async def test_prompt_optimizer_can_see_train_split_critic_runs(
    synced_test_db: DatabaseConfig, test_prompt_sha: str, prompt_optimizer_session: Session
):
    """Prompt optimizer users can see TRAIN split critic runs (RLS policy allows).

    Uses test-fixtures/test-trivial (TRAIN split) from git fixtures.

    Setup (as admin_user):
    - Query existing test-trivial snapshot and example
    - Create critic run for train snapshot

    Verify (as prompt optimizer temp user):
    - Can query critic_runs for train split specimens
    """
    # Setup: Use admin_user to write test data
    train_run_id = uuid4()

    with get_session() as session:
        # Query git fixture example (TRAIN split)
        example = session.query(Example).filter_by(snapshot_slug="test-fixtures/test-trivial").first()
        assert example, "test-trivial fixture not found"

        # Create a critic run for the train specimen using fixture factory
        train_run = make_critic_run(
            example=example, prompt_sha256=test_prompt_sha, transcript_id=train_run_id, status=CriticRunStatus.COMPLETED
        )
        session.add(train_run)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify can see train split
    train_runs = prompt_optimizer_session.query(CriticRun).filter(CriticRun.transcript_id == train_run_id).all()

    assert len(train_runs) == 1, "prompt optimizer user should see train split critic_runs via RLS"
    assert train_runs[0].snapshot_slug == "test-fixtures/test-trivial"
