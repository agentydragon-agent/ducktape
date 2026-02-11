from __future__ import annotations

from collections.abc import Callable, Iterator
import os
from typing import TYPE_CHECKING, Any

import pytest

from adgn.agent.server.app import create_app
from tests.agent.helpers import start_uvicorn_app

# Auto-apply e2e marker to all tests in this directory
pytestmark = [pytest.mark.e2e]

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Playwright


@pytest.fixture
def browser_name() -> str:
    return os.environ.get("ADGN_E2E_BROWSER", "chromium")


@pytest.fixture
def e2e_headless() -> bool:
    headless_env = os.environ.get("ADGN_E2E_HEADLESS")
    if headless_env is None:
        return True
    return headless_env.strip().lower() not in {"0", "false", "no", "off"}


@pytest.fixture(scope="session")
def playwright_sync() -> Iterator[Playwright]:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as manager:
        yield manager


@pytest.fixture
def browser(playwright_sync: Playwright, browser_name: str, e2e_headless: bool) -> Iterator[Browser]:
    browser_type = getattr(playwright_sync, browser_name, None)
    if browser_type is None:
        raise RuntimeError(f"Unsupported Playwright browser: {browser_name}")
    browser = browser_type.launch(headless=e2e_headless)
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    try:
        yield page
    finally:
        try:
            page.close()
        finally:
            context.close()


@pytest.fixture
def run_server(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Start the UI server (FastAPI+WS) on a background thread; yield base_url and stopper.

    Uses a per-test SQLite DB via ADGN_AGENT_DB_PATH; serves built static assets.
    Shared by e2e UI tests to avoid duplication.
    """

    def _start(client_factory: Callable[[str], Any] | None = None) -> dict[str, Any]:
        db_path = tmp_path / "agent.sqlite"
        monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(db_path))
        app = create_app(require_static_assets=True)
        result: dict[str, Any] = start_uvicorn_app(app)
        return result

    return _start


## patch_model fixture retired; tests pass a client_factory to run_server instead
