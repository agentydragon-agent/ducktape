"""Public Augur product-surface browser smoke test against the Bazel-runnable server."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_bazel

from util.bazel.runfiles import get_required_path
from util.net import pick_free_port
from util.testing.undeclared_outputs import undeclared_outputs_dir

pytest_plugins = ("util.playwright",)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Playwright


@pytest.fixture
def browser(playwright_sync: Playwright) -> Iterator[Browser]:
    chromium_root = os.environ.get("CHROMIUM_HEADLESS_SHELL", "")
    executable = str(Path(chromium_root) / "chrome-linux" / "headless_shell") if chromium_root else None
    browser = playwright_sync.chromium.launch(
        headless=True,
        executable_path=executable,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        yield page
    finally:
        try:
            page.close()
        finally:
            context.close()


@pytest.fixture
def augur_server(tmp_path: Path) -> Iterator[str]:
    out = undeclared_outputs_dir()
    server_log = (out / "augur-server.log").open("w")
    port = pick_free_port("127.0.0.1")
    server = subprocess.Popen(
        [
            str(get_required_path("_main/augur/dev")),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--config",
            str(get_required_path("_main/augur/api/testdata/config.yaml")),
        ],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "MPLCONFIGDIR": str(tmp_path / "matplotlib"),
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        stdout=server_log,
        stderr=server_log,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Augur server exited early with code {server.returncode}; see {server_log.name}")
            try:
                with urllib.request.urlopen(f"{origin}/healthz", timeout=1) as response:
                    if response.status == 200 and response.read().decode() == "ok\n":
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        else:
            raise RuntimeError(f"Augur server did not start within 30s; see {server_log.name}")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        server_log.close()


def test_product_shell_renders_metric_fan_charts(page: Page, augur_server: str) -> None:
    """Smoke-test the product surface end-to-end: load `/product`, select a few metrics,
    confirm the matching fan chart renders for each."""
    page.goto(f"{augur_server}/product", wait_until="domcontentloaded")
    page.locator("[data-augur-surface='product']").wait_for(state="visible", timeout=15_000)
    page.get_by_label("Metric to plot").wait_for(state="visible", timeout=15_000)
    page.get_by_label("Metric to plot").select_option("cash_usd")
    page.locator("[data-product-fan-chart='cashUsd']").wait_for(state="visible", timeout=30_000)
    page.get_by_label("Metric to plot").select_option("holding_value_usd")
    page.locator("[data-product-fan-chart='holdingValueUsd']").wait_for(state="visible", timeout=30_000)


if __name__ == "__main__":
    pytest_bazel.main()
