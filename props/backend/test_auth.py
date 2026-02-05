"""Unit tests for auth module - get_agent_db credential passthrough."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_bazel
from fastapi import HTTPException

from props.backend.auth import AuthContext, get_agent_db
from props.db.config import DatabaseConfig
from props.db.database import Database


def _exhaust_generator(gen):
    """Run a FastAPI dependency generator and return the yielded value."""
    value = next(gen)
    with contextlib.suppress(StopIteration):
        next(gen)
    return value


def test_get_agent_db_admin_returns_admin_db():
    """Admin users get the shared admin database connection."""
    admin_db = MagicMock(spec=Database)
    auth = AuthContext.localhost_admin()

    gen = get_agent_db(admin_db=admin_db, auth=auth)
    db = _exhaust_generator(gen)
    assert db is admin_db


def test_get_agent_db_admin_with_credentials_returns_admin_db():
    """Admin users with explicit credentials still get the admin connection."""
    admin_db = MagicMock(spec=Database)
    auth = AuthContext.admin(username="postgres", password="secret")

    gen = get_agent_db(admin_db=admin_db, auth=auth)
    db = _exhaust_generator(gen)
    assert db is admin_db


def test_get_agent_db_anonymous_raises_401():
    """Anonymous (unauthenticated) callers get 401."""
    admin_db = MagicMock(spec=Database)
    auth = AuthContext.anonymous()

    gen = get_agent_db(admin_db=admin_db, auth=auth)
    with pytest.raises(HTTPException) as exc_info:
        next(gen)
    assert exc_info.value.status_code == 401


def test_get_agent_db_agent_creates_per_request_db(monkeypatch: pytest.MonkeyPatch):
    """Agent callers get a per-request Database with their credentials."""
    run_id = uuid4()
    admin_config = DatabaseConfig(host="localhost", port=5432, database="testdb", user="admin", password="admin_pass")
    admin_db = MagicMock(spec=Database)
    admin_db.config = admin_config

    auth = AuthContext.agent(username=f"agent_{run_id}", password="agent_pass", agent_run_id=run_id)

    # Mock Database constructor to avoid actual Postgres connection
    created_dbs: list[tuple[DatabaseConfig, bool]] = []

    def mock_init(self, config, *, _per_request=False):
        created_dbs.append((config, _per_request))
        self._config = config
        self._engine = MagicMock()

    monkeypatch.setattr(Database, "__init__", mock_init)
    monkeypatch.setattr(Database, "dispose", lambda self: None)

    gen = get_agent_db(admin_db=admin_db, auth=auth)
    db = next(gen)

    # Verify a new Database was created with agent credentials and per_request=True
    assert len(created_dbs) == 1
    config, per_request = created_dbs[0]
    assert config.user == f"agent_{run_id}"
    assert config.password == "agent_pass"
    assert config.host == "localhost"
    assert config.database == "testdb"
    assert per_request is True

    # Verify it's not the admin db
    assert db is not admin_db

    # Cleanup
    with contextlib.suppress(StopIteration):
        next(gen)


def test_get_agent_db_agent_disposes_on_cleanup(monkeypatch: pytest.MonkeyPatch):
    """Agent per-request database is disposed after the request."""
    run_id = uuid4()
    admin_config = DatabaseConfig(host="localhost", port=5432, database="testdb", user="admin", password="admin_pass")
    admin_db = MagicMock(spec=Database)
    admin_db.config = admin_config

    auth = AuthContext.agent(username=f"agent_{run_id}", password="agent_pass", agent_run_id=run_id)

    disposed = []

    def mock_init(self, config, *, _per_request=False):
        self._config = config
        self._engine = MagicMock()

    monkeypatch.setattr(Database, "__init__", mock_init)
    monkeypatch.setattr(Database, "dispose", lambda self: disposed.append(True))

    gen = get_agent_db(admin_db=admin_db, auth=auth)
    next(gen)  # Get the yielded db

    assert len(disposed) == 0  # Not disposed yet

    # Exhaust the generator (triggers finally block)
    with contextlib.suppress(StopIteration):
        next(gen)

    assert len(disposed) == 1  # Disposed after cleanup


if __name__ == "__main__":
    pytest_bazel.main()
