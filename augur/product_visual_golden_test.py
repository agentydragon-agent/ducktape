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
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import pytest
import pytest_bazel

from util.bazel.runfiles import get_required_path
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


class _ProductBundleHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        url_path = unquote(urlparse(self.path).path)
        rel_path = Path(url_path.lstrip("/"))
        if (
            url_path == "/"
            or rel_path.is_absolute()
            or ".." in rel_path.parts
            or not (Path(self.directory) / rel_path).exists()
        ):
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture(scope="module")
def product_static_server() -> Iterator[str]:
    dist_dir = get_required_path("_main/augur/frontend/dist/index.html").parent

    def handler(*args: Any, **kwargs: Any) -> _ProductBundleHandler:
        return _ProductBundleHandler(*args, directory=str(dist_dir), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


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
    page.locator("[data-product-empty-state='cash-runway']").wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="Augur", exact=True).wait_for(state="visible", timeout=30_000)
    page.get_by_text("Product projection").first.wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="Cash runway").first.wait_for(state="visible", timeout=30_000)
    assert page.get_by_text("Terminal scenario comparison").count() == 0
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.evaluate("() => document.fonts.ready.then(() => true)")


def _render_product_page(page: Page, origin: str, out_dir: Path, suffix: str) -> Path:
    page.goto(f"{origin}/product", wait_until="networkidle", timeout=60_000)
    _wait_for_product_page(page)
    page.goto(page.url, wait_until="networkidle", timeout=60_000)
    _wait_for_product_page(page)
    actual_path = out_dir / f"{PRODUCT_GOLDEN_NAME}.{suffix}.png"
    page.screenshot(path=str(actual_path), full_page=True, animations="disabled", caret="hide", scale="css")
    return actual_path


def test_product_frontend_visual_golden(page: Page, product_static_server: str, tmp_path: Path) -> None:
    undeclared_dir = undeclared_outputs_dir()
    first_path = _render_product_page(page, product_static_server, tmp_path, "first")
    second_path = _render_product_page(page, product_static_server, tmp_path, "second")
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
