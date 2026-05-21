"""Visual golden for the product-language Augur frontend surface.

Update flow for intentional product frontend changes:

    nix develop --command bazelisk test //augur:product_visual_golden_test \
        --test_env=UPDATE_GOLDEN=1 \
        --remote_upload_local_results=false --nocache_test_results

Then copy the produced PNG from undeclared outputs into
`augur/frontend/__screenshots__/` and rerun this test without `UPDATE_GOLDEN`.
With BuildBuddy/RBE, use the invocation id printed by Bazel:

    for f in product_cash_runway; do
        bbapi artifact "$INV" "test.outputs/$f.png" \
            > "augur/frontend/__screenshots__/$f.png"
    done
"""

from __future__ import annotations

import os
import shutil
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
from util.testing.frontend_visual import (
    deterministic_browser_context,
    deterministic_style,
    launch_deterministic_browser,
)
from util.testing.png_diff import assert_png_matches_golden
from util.testing.undeclared_outputs import undeclared_outputs_dir

pytest_plugins = ("util.playwright",)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Playwright, ViewportSize


SCREENSHOT_VIEWPORT: ViewportSize = {"width": 1280, "height": 1000}
FROZEN_NOW_MS = 1_779_768_000_000  # 2026-05-15T12:00:00Z.
PRODUCT_GOLDEN_NAME = "product_cash_runway"


@pytest.fixture(scope="module")
def augur_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    tmp_path = tmp_path_factory.mktemp("augur-product-visual-server")
    out = undeclared_outputs_dir()
    server_log = (out / "augur-product-visual-server.log").open("w")
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
    try:
        deadline = time.monotonic() + 30
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


@pytest.fixture
def browser(playwright_sync: Playwright) -> Iterator[Browser]:
    browser = launch_deterministic_browser(playwright_sync)
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = deterministic_browser_context(browser, viewport=SCREENSHOT_VIEWPORT, frozen_now_ms=FROZEN_NOW_MS)
    page = context.new_page()
    try:
        yield page
    finally:
        try:
            page.close()
        finally:
            context.close()


def _wait_for_product_page(page: Page) -> None:
    page.add_style_tag(content=deterministic_style())
    page.locator("[data-augur-surface='product']").wait_for(state="visible", timeout=30_000)
    page.locator("[data-product-fan-chart='netWorthUsd']").wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="Augur", exact=True).wait_for(state="visible", timeout=30_000)
    page.get_by_text("Product projection").first.wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="Cash projection fan").first.wait_for(state="visible", timeout=30_000)
    page.get_by_label("Metric to plot").wait_for(state="visible", timeout=30_000)
    page.wait_for_function(
        """
        () => {
          const chart = document.querySelector("[data-product-fan-chart='netWorthUsd'] svg[role='img']");
          if (!chart) return false;
          const heights = Array.from(chart.querySelectorAll("polygon")).map((polygon) => {
            const points = (polygon.getAttribute("points") || "")
              .trim()
              .split(/\\s+/)
              .map((point) => Number(point.split(",")[1]))
              .filter(Number.isFinite);
            return points.length ? Math.max(...points) - Math.min(...points) : 0;
          });
          return Math.max(0, ...heights) >= 80;
        }
        """,
        timeout=30_000,
    )
    assert page.get_by_text("Terminal scenario comparison").count() == 0
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.evaluate("() => document.fonts.ready.then(() => true)")


def _select_first_rollout(page: Page) -> None:
    page.locator("[data-product-rollout-sliver]").first.click()
    page.locator("[data-product-selected-rollout-line]").wait_for(state="visible", timeout=30_000)
    page.locator(r"text=/Seed \d+ - failed m\d+/").wait_for(state="visible", timeout=30_000)


def _render_product_page(page: Page, origin: str, out_dir: Path, suffix: str) -> Path:
    page.goto(f"{origin}/product", wait_until="networkidle", timeout=60_000)
    _wait_for_product_page(page)
    page.goto(page.url, wait_until="networkidle", timeout=60_000)
    _wait_for_product_page(page)
    _select_first_rollout(page)
    actual_path = out_dir / f"{PRODUCT_GOLDEN_NAME}.{suffix}.png"
    page.screenshot(path=str(actual_path), full_page=True, animations="disabled", caret="hide", scale="css")
    return actual_path


def test_product_frontend_visual_golden(page: Page, augur_server: str, tmp_path: Path) -> None:
    undeclared_dir = undeclared_outputs_dir()
    first_path = _render_product_page(page, augur_server, tmp_path, "first")
    second_path = _render_product_page(page, augur_server, tmp_path, "second")
    if first_path.read_bytes() != second_path.read_bytes():
        shutil.copy(first_path, undeclared_dir / f"{PRODUCT_GOLDEN_NAME}.first.png")
        shutil.copy(second_path, undeclared_dir / f"{PRODUCT_GOLDEN_NAME}.second.png")
        raise AssertionError(
            f"{PRODUCT_GOLDEN_NAME} visual render is not deterministic across reloads; "
            f"inspect {PRODUCT_GOLDEN_NAME}.first.png and {PRODUCT_GOLDEN_NAME}.second.png in {undeclared_dir}"
        )

    out_name = f"{PRODUCT_GOLDEN_NAME}.png"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        shutil.copy(first_path, undeclared_dir / out_name)
        return

    try:
        expected_path = get_required_path(f"_main/augur/frontend/__screenshots__/{out_name}")
    except RuntimeError:
        shutil.copy(first_path, undeclared_dir / out_name)
        raise AssertionError(
            f"No Augur product visual golden checked in for {out_name}. Re-run with UPDATE_GOLDEN=1 "
            f"and copy the produced PNG from undeclared outputs into augur/frontend/__screenshots__/."
        ) from None

    assert_png_matches_golden(
        first_path,
        expected_path,
        name=PRODUCT_GOLDEN_NAME,
        out_dir=undeclared_dir,
        tolerance=0.0,
        intensity_threshold=1,
    )


if __name__ == "__main__":
    pytest_bazel.main()
