from __future__ import annotations

from typing import Any, Callable

import pytest

from adgn.agent.server.app import create_app
from tests.agent.helpers import start_uvicorn_app


@pytest.fixture
def run_server(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Start the UI server (FastAPI+WS) on a background thread; yield base_url and stopper.

    Uses a per-test SQLite DB via ADGN_AGENT_DB_PATH; serves built static assets.
    Shared by e2e UI tests to avoid duplication.
    """

    def _start(client_factory: Callable[[str], Any] | None = None) -> dict[str, Any]:
        db_path = tmp_path / "agent.sqlite"
        monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(db_path))
        app = create_app(require_static_assets=True, client_factory=client_factory)
        return start_uvicorn_app(app)

    return _start


## patch_model fixture retired; tests pass a client_factory to run_server instead
