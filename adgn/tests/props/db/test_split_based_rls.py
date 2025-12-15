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

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, FalsePositive, Snapshot, TruePositive
from adgn.props.db.prompt_optimizer_user_manager import PromptOptimizerUserManager
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import FalsePositiveOccurrence, TruePositiveOccurrence
from tests.props.conftest import TEST_FILES_HASH, TEST_FILES_LIST, make_critic_success

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.mark.asyncio
async def test_prompt_optimizer_cannot_see_test_split_snapshots(test_db):
    """Prompt optimizer users cannot see TEST split snapshots (RLS policy blocks).

    Setup (as admin_user):
    - Create test snapshot

    Verify (as prompt optimizer temp user):
    - Cannot query snapshots for test split
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    with get_session() as session:
        test_specimen = Snapshot(slug="crush/test-specimen", split="test", source=LocalSource(vcs="local", root="."))
        session.merge(test_specimen)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify RLS blocks test split
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            test_snapshots = session.query(Snapshot).filter(Snapshot.slug == "crush/test-specimen").all()

            assert len(test_snapshots) == 0, "prompt optimizer user should not see test split snapshots via RLS"

        user_engine.dispose()


@pytest.mark.asyncio
async def test_prompt_optimizer_can_see_train_split_snapshots(test_db):
    """Prompt optimizer users can see TRAIN split snapshots (RLS policy allows).

    Setup (as admin_user):
    - Create train snapshot

    Verify (as prompt optimizer temp user):
    - Can query snapshots for train split
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    with get_session() as session:
        train_specimen = Snapshot(
            slug="ducktape/2025-11-26-00", split="train", source=LocalSource(vcs="local", root=".")
        )
        session.merge(train_specimen)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify RLS allows train split
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            train_snapshots = session.query(Snapshot).filter(Snapshot.slug == "ducktape/2025-11-26-00").all()

            assert len(train_snapshots) == 1, (
                f"prompt optimizer user should see train split snapshots via RLS (expected_run_id={run_id})"
            )
            assert train_snapshots[0].split == "train"

        user_engine.dispose()


@pytest.mark.asyncio
async def test_prompt_optimizer_cannot_see_valid_split_true_positives(test_db):
    """Prompt optimizer users CANNOT see valid split true positives (RLS policy blocks).

    Setup (as admin_user):
    - Create valid specimen
    - Create true positive for valid specimen

    Verify (as prompt optimizer temp user):
    - CANNOT query true positives for valid specimens (returns 0 rows)
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    with get_session() as session:
        valid_specimen = Snapshot(slug="valid/spec-test", split="valid", source=LocalSource(vcs="local", root="."))
        session.merge(valid_specimen)
        session.commit()

        # Create TP for valid specimen
        tp = TruePositive(
            snapshot_slug="valid/spec-test",
            tp_id="test-tp-001",
            rationale="Test issue",
            occurrences=[
                TruePositiveOccurrence(
                    occurrence_id="occ-1",
                    files={Path("test.py"): None},
                    expect_caught_from={frozenset([Path("test.py")])},
                )
            ],
        )
        session.add(tp)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify RLS blocks valid split
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            # Should NOT see true positives for valid specimen
            valid_tps = session.query(TruePositive).filter(TruePositive.snapshot_slug == "valid/spec-test").all()
            assert len(valid_tps) == 0, "prompt optimizer user should NOT see valid split true_positives via RLS"

        user_engine.dispose()


@pytest.mark.asyncio
async def test_prompt_optimizer_can_see_train_split_false_positives(test_db):
    """Prompt optimizer users can see TRAIN split false positives (RLS policy allows).

    Setup (as admin_user):
    - Create train specimen
    - Create false positive for train specimen

    Verify (as prompt optimizer temp user):
    - Can query false positives for train specimens
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    with get_session() as session:
        train_specimen = Snapshot(slug="train/fp-test", split="train", source=LocalSource(vcs="local", root="."))
        session.merge(train_specimen)
        session.commit()

        # Create FP for train specimen
        fp = FalsePositive(
            snapshot_slug="train/fp-test",
            fp_id="test-fp-001",
            rationale="Known acceptable pattern",
            occurrences=[
                FalsePositiveOccurrence(
                    occurrence_id="occ-fp-1", files={Path("foo.py"): None}, relevant_files={Path("foo.py")}
                )
            ],
        )
        session.add(fp)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify can see train FPs
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            train_fps = session.query(FalsePositive).filter(FalsePositive.snapshot_slug == "train/fp-test").all()
            assert len(train_fps) == 1, "prompt optimizer user should see train split false_positives via RLS"
            assert train_fps[0].fp_id == "test-fp-001"

        user_engine.dispose()


@pytest.mark.asyncio
async def test_prompt_optimizer_cannot_see_test_split_critic_runs(test_db, test_prompt_sha):
    """Prompt optimizer users cannot see TEST split critic runs (RLS policy blocks).

    Setup (as admin_user):
    - Create test snapshot
    - Create critic run for test snapshot

    Verify (as prompt optimizer temp user):
    - Cannot query critic_runs for test split specimens
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    with get_session() as session:
        test_specimen = Snapshot(slug="test/critic-run-test", split="test", source=LocalSource(vcs="local", root="."))
        session.merge(test_specimen)
        session.commit()

        # Create a critic run for the test specimen
        test_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=test_prompt_sha,
            snapshot_slug="test/critic-run-test",
            model="test-model",
            files=TEST_FILES_LIST,
            files_hash=TEST_FILES_HASH,
            output=make_critic_success(),
        )
        session.add(test_run)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify RLS blocks test split
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            test_runs = session.query(CriticRun).filter(CriticRun.snapshot_slug == "test/critic-run-test").all()

            assert len(test_runs) == 0, "prompt optimizer user should not see test split critic_runs via RLS"

        user_engine.dispose()


@pytest.mark.asyncio
async def test_prompt_optimizer_can_see_train_split_critic_runs(test_db, test_prompt_sha):
    """Prompt optimizer users can see TRAIN split critic runs (RLS policy allows).

    Setup (as admin_user):
    - Create train snapshot
    - Create critic run for train snapshot

    Verify (as prompt optimizer temp user):
    - Can query critic_runs for train split specimens
    """
    config = test_db  # Use test database config from fixture
    run_id = uuid4()

    # Setup: Use admin_user to write test data
    train_run_id = uuid4()

    with get_session() as session:
        train_specimen = Snapshot(
            slug="train/critic-run-test", split="train", source=LocalSource(vcs="local", root=".")
        )
        session.merge(train_specimen)
        session.commit()

        # Create a critic run for the train specimen
        train_run = CriticRun(
            transcript_id=train_run_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug="train/critic-run-test",
            model="test-model",
            files=TEST_FILES_LIST,
            files_hash=TEST_FILES_HASH,
            output=make_critic_success(),
        )
        session.add(train_run)
        session.commit()

    # Verify: Connect as prompt optimizer temp user and verify can see train split
    async with PromptOptimizerUserManager(config.admin, run_id) as creds:
        user_config = config.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with Session(user_engine) as session:
            train_runs = session.query(CriticRun).filter(CriticRun.transcript_id == train_run_id).all()

            assert len(train_runs) == 1, "prompt optimizer user should see train split critic_runs via RLS"
            assert train_runs[0].snapshot_slug == "train/critic-run-test"

        user_engine.dispose()
