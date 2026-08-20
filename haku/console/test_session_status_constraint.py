"""The lazy-allocation status widens safely before any session writes it."""

from __future__ import annotations

import datetime
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from haku.console.database_migrate import apply_migrations, sync_database_url

_NOW = datetime.datetime(2026, 8, 18, tzinfo=datetime.UTC)
_PREVIOUS_STATUSES = ("provisioning", "ready", "responding", "closing", "closed", "failed")


@pytest.fixture
def engine(db_url: str) -> Generator[Engine]:
    created = create_engine(sync_database_url(db_url))
    try:
        yield created
    finally:
        created.dispose()


def _operator(conn: Connection) -> UUID:
    operator_id = uuid4()
    conn.execute(
        text("INSERT INTO operators (operator_id, status, created_at, updated_at) VALUES (:id, 'active', :n, :n)"),
        {"id": operator_id, "n": _NOW},
    )
    return operator_id


def _insert_session(
    conn: Connection,
    status: str,
    *,
    fingerprint: bytes | None = b"fingerprint",
    lease_expires_at: datetime.datetime | None = _NOW,
) -> None:
    operator_id, conversation_id = _operator(conn), uuid4()
    conn.execute(
        text(
            "INSERT INTO conversation (conversation_id, operator_id, runtime_kind, created_at) VALUES (:id, :o, 'claude_code', :n)"
        ),
        {"id": conversation_id, "o": operator_id, "n": _NOW},
    )
    conn.execute(
        text(
            "INSERT INTO sessions (session_id, operator_id, conversation_id, status, bridge_token_fingerprint, "
            "lease_expires_at, created_at, updated_at) "
            "VALUES (:session_id, :operator_id, :conversation_id, :status, :fingerprint, :lease, :n, :n)"
        ),
        {
            "session_id": uuid4(),
            "operator_id": operator_id,
            "conversation_id": conversation_id,
            "status": status,
            "fingerprint": fingerprint,
            "lease": lease_expires_at,
            "n": _NOW,
        },
    )


def test_idle_is_admitted_only_after_the_rollout_migration(db_url: str, engine: Engine) -> None:
    apply_migrations(db_url, "0088")
    with engine.begin() as conn, pytest.raises(IntegrityError, match="ck_sessions_status"):
        _insert_session(conn, "idle")

    apply_migrations(db_url)
    with engine.begin() as conn:
        _insert_session(conn, "idle", fingerprint=None, lease_expires_at=None)


@pytest.mark.parametrize("status", _PREVIOUS_STATUSES)
def test_a_replica_on_the_previous_image_still_writes_every_status_it_knows(
    db_url: str, engine: Engine, status: str
) -> None:
    """The roll's other direction, and the whole safety argument: the previous image keeps serving
    against this schema, so a narrowing must reject only what nothing writes."""
    apply_migrations(db_url)
    with engine.begin() as conn:
        _insert_session(conn, status)


def test_the_widening_does_not_admit_unknown_statuses(db_url: str, engine: Engine) -> None:
    apply_migrations(db_url)
    with engine.begin() as conn, pytest.raises(IntegrityError, match="ck_sessions_status"):
        _insert_session(conn, "sleeping")


@pytest.mark.parametrize(("status", "fingerprint"), [("idle", b"credential"), ("provisioning", None), ("ready", None)])
def test_only_an_idle_session_lacks_a_bridge_credential(
    db_url: str, engine: Engine, status: str, fingerprint: bytes | None
) -> None:
    apply_migrations(db_url)
    with engine.begin() as conn, pytest.raises(IntegrityError, match="ck_sessions_idle_bridge_token"):
        _insert_session(conn, status, fingerprint=fingerprint)


@pytest.mark.parametrize("status", ["closing", "closed", "failed"])
def test_an_unallocated_session_may_end_without_a_credential(db_url: str, engine: Engine, status: str) -> None:
    apply_migrations(db_url)
    with engine.begin() as conn:
        _insert_session(conn, status, fingerprint=None, lease_expires_at=None)


@pytest.mark.parametrize(("status", "lease"), [("idle", _NOW), ("provisioning", None), ("ready", None)])
def test_only_an_idle_session_lacks_a_lease(
    db_url: str, engine: Engine, status: str, lease: datetime.datetime | None
) -> None:
    apply_migrations(db_url)
    with engine.begin() as conn, pytest.raises(IntegrityError, match="ck_sessions_idle_lease"):
        _insert_session(conn, status, fingerprint=None if status == "idle" else b"fingerprint", lease_expires_at=lease)


if __name__ == "__main__":
    pytest_bazel.main()
