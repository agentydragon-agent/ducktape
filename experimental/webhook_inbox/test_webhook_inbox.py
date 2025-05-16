"""Unit tests for webhook_inbox.py FastAPI application.

The tests spin-up the app with an isolated SQLite database that lives in a
temporary directory (one per test session). This is achieved by setting the
``DB_PATH`` environment variable *before* importing the application module so
that the global ``DB`` constant inside ``webhook_inbox`` points at the fresh
database file.

Only behaviour that can be reasoned about without starting an actual HTTP
server is verified – a ``TestClient`` from ``fastapi`` is used to exercise the
end-points.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_and_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a tuple **(client, module)** with an isolated database.

    A brand-new SQLite file is created under *tmp_path* and its location is
    exposed to the application via the ``DB_PATH`` environment variable.  The
    application module is **re-imported** so that its module-level constants
    take the new environment into account.
    """

    # Point the application at a dedicated temporary database file.
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    # (Re-)import the module *after* the environment variable is set so that
    # webhook_inbox.DB picks up the correct path.  If the module has already
    # been imported by another test we first remove it from ``sys.modules`` to
    # force a clean import.
    if "webhook_inbox" in sys.modules:
        del sys.modules["webhook_inbox"]

    app_module = importlib.import_module("webhook_inbox")

    # The FastAPI TestClient opens the app in a background thread and handles
    # requests entirely in-process – no actual sockets are touched.
    client = TestClient(app_module.app)

    # Yield to the test function and close the client afterwards to ensure a
    # clean shutdown of the background thread.
    try:
        yield client, app_module
    finally:
        client.close()


def test_ingest_persists_event(app_and_client):
    """Posting a UTF-8 payload should be accepted and persisted in the DB."""

    client, app = app_and_client

    payload = "Hello, webhook!"
    response = client.post("/", data=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # The payload must now be stored in the *events* table.
    row = app.CONN.execute("SELECT payload FROM events").fetchone()
    assert row is not None
    assert row[0] == payload


def test_payload_too_large(app_and_client):
    """A payload that exceeds ``MAX_PAYLOAD`` must be rejected with 413."""

    client, app = app_and_client

    oversized = "x" * (app.MAX_PAYLOAD + 1)
    response = client.post("/", data=oversized)

    assert response.status_code == 413


def test_invalid_utf8_payload(app_and_client):
    """Binary garbage that is not UTF-8 should raise HTTP 400."""

    client, _ = app_and_client

    # 0x80 is not valid as a lone start byte in UTF-8.
    binary_data = b"\x80\x80"
    response = client.post("/", data=binary_data, headers={"Content-Type": "application/octet-stream"})

    assert response.status_code == 400


def test_root_redirect_and_before_param(app_and_client):
    """``GET /`` should redirect and improper ``before`` parameters are invalid."""

    client, _ = app_and_client

    # Without the *before* query parameter the root must redirect.
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/?before=")

    # A non-integer *before* value should yield 400.
    bad = client.get("/?before=not_an_int")
    assert bad.status_code == 400
