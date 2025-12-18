"""Shared fixtures and helpers for critic integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from adgn.props.critic.submit_server import CriticSubmitServer
from adgn.props.critic.user_manager import CriticUserManager
from adgn.props.db import get_session
from adgn.props.db.models import CriticRunStatus
from adgn.props.db.snapshots import DBReportedIssue
from adgn.props.models.critic_scopes import ExplicitFileScope
from tests.props.conftest import get_or_create_example, make_critic_run

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from sqlalchemy.engine import Connection

    from adgn.props.hydration import SnapshotHydrator
    from adgn.props.ids import SnapshotSlug

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.fixture
def test_critic_run(test_db, test_snapshot, test_prompt_sha):
    """Create test critic run.

    Returns:
        UUID of the created critic run
    """
    with get_session() as session:
        # Create critic run (snapshot already created by test_snapshot fixture)
        # Using test.py to match the file created by snapshot_mount fixture
        scope = ExplicitFileScope(files=["test.py"])
        example = get_or_create_example(session, test_snapshot, scope)

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha, status=CriticRunStatus.IN_PROGRESS)
        session.add(critic_run)
        session.commit()

        return critic_run.id


@pytest.fixture
async def temp_creds(test_db, test_critic_run):
    """Create temporary database user with RLS scoping.

    Returns:
        TempUserCredentials for the critic agent
    """
    async with CriticUserManager(test_db.admin, test_critic_run) as creds:
        yield creds


@pytest.fixture
def snapshot_mount(tmp_path):
    """Create mock snapshot mount directory.

    Returns:
        Path to the snapshot mount directory
    """
    mount = tmp_path / "snapshot"
    mount.mkdir()
    (mount / "test.py").write_text("# test file\n")
    return mount


@pytest.fixture
def temp_engine(test_db, temp_creds) -> Engine:
    """Create SQLAlchemy engine using temporary user credentials.

    Returns:
        SQLAlchemy Engine connected as the temporary user
    """
    user_config = test_db.admin.with_user(temp_creds)
    return create_engine(user_config.url())


def insert_issue(
    conn: Connection, issue_id_or_data: str | dict[str, str] | DBReportedIssue, rationale: str | None = None
) -> None:
    """Insert a reported issue using temp user credentials.

    Accepts three formats:
    - Old style (backwards compatible): insert_issue(conn, "my-id", "My rationale")
    - Dict: insert_issue(conn, {"id": "my-id", "rationale": "..."})
    - Pydantic: insert_issue(conn, DBReportedIssue(id="my-id", rationale="..."))

    Args:
        conn: Database connection (must be from temp user engine)
        issue_id_or_data: Either:
            - string issue_id (old style, requires rationale parameter)
            - dict {"id": str, "rationale": str}
            - DBReportedIssue object
        rationale: Issue rationale (only used with string issue_id)
    """
    # Handle different input formats
    if isinstance(issue_id_or_data, str):
        # Old style: two positional args
        if rationale is None:
            raise ValueError("When passing issue_id as string, rationale is required")
        issue_id_val = issue_id_or_data
        rationale_val = rationale
    elif isinstance(issue_id_or_data, dict):
        # New style: dict
        issue_id_val = issue_id_or_data["id"]
        rationale_val = issue_id_or_data["rationale"]
    else:
        # New style: Pydantic DBReportedIssue
        issue_id_val = issue_id_or_data.id
        rationale_val = issue_id_or_data.rationale

    conn.execute(
        text("""
            INSERT INTO reported_issues (issue_id, rationale)
            VALUES (:issue_id, :rationale)
        """),
        {"issue_id": issue_id_val, "rationale": rationale_val},
    )


def insert_occurrence(conn: Connection, issue_id: str, locations_json: str) -> None:
    """Insert a reported issue occurrence using temp user credentials.

    Args:
        conn: Database connection (must be from temp user engine)
        issue_id: Issue ID this occurrence belongs to
        locations_json: JSON array of DBLocationAnchor objects
            Example: '[{"file": "test.py", "start_line": 10, "end_line": 20}]'
    """
    conn.execute(
        text("""
            INSERT INTO reported_issue_occurrences
              (reported_issue_id, locations)
            VALUES (:issue_id, CAST(:locations AS jsonb))
        """),
        {"issue_id": issue_id, "locations": locations_json},
    )


@pytest.fixture
def submit_server(test_critic_run, test_snapshot, snapshot_mount, all_files_scope):
    """Create a critic submit server for testing.

    Uses mock snapshot_mount directory for unit tests.
    For integration tests with real hydrated snapshots, use hydrated_test_snapshot fixture.

    Returns:
        CriticSubmitServer instance for the test critic run
    """
    return CriticSubmitServer(
        critic_run_id=test_critic_run,
        snapshot_slug=test_snapshot,
        scope=all_files_scope,
        snapshot_hydrated_path=snapshot_mount,
    )


@pytest_asyncio.fixture
async def hydrated_test_snapshot(
    test_snapshot: SnapshotSlug, test_specimens_hydrator: SnapshotHydrator
) -> AsyncGenerator[Path, None]:
    """Provide actually hydrated snapshot for integration testing.

    Hydrates test_snapshot using test_specimens_hydrator.
    Yields the content_root path where hydrated files are located.

    Yields:
        Path to hydrated snapshot content root
    """
    async with test_specimens_hydrator.hydrate(test_snapshot) as hydrated:
        yield hydrated.content_root
