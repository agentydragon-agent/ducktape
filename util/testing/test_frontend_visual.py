"""Verify the Playwright launcher pins Chromium's generic font families."""

from __future__ import annotations

import asyncio

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_bazel
from playwright.async_api import Page, Playwright

from util.testing.frontend_visual import DISABLE_ANIMATIONS_CSS, deterministic_browser_context

# gazelle:include_dep //util:playwright

pytest_plugins = ("util.playwright",)


@pytest.fixture
def los_angeles_process_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    # Before `playwright` starts the driver, whose environment the browser inherits.
    monkeypatch.setenv("TZ", "America/Los_Angeles")


async def _platform_families(page: Page, selector: str) -> list[str]:
    session = await page.context.new_cdp_session(page)
    await session.send("DOM.enable")
    await session.send("CSS.enable")
    root = (await session.send("DOM.getDocument"))["root"]
    node_id = (await session.send("DOM.querySelector", {"nodeId": root["nodeId"], "selector": selector}))["nodeId"]
    fonts = (await session.send("CSS.getPlatformFontsForNode", {"nodeId": node_id}))["fonts"]
    await session.detach()
    return [font["familyName"] for font in fonts]


async def test_generic_families_are_browser_pinned(playwright: Playwright) -> None:
    async with deterministic_browser_context(
        playwright, viewport={"width": 800, "height": 600}, frozen_now_ms=0
    ) as context:
        page = await context.new_page()
        await page.set_content(
            """
            <style>
              #serif { font-family: serif; }
              #sans { font-family: sans-serif; }
              #mono { font-family: monospace; }
              #system { font-family: system-ui; }
              #explicit { font-family: "Liberation Mono"; }
            </style>
            <div id="serif">Serif sample</div>
            <div id="sans">Sans sample</div>
            <div id="mono">Mono sample</div>
            <div id="system">System sample</div>
            <pre id="pre"><code id="code">const answer = 42;</code></pre>
            <div id="explicit">Explicit sample</div>
            """
        )
        for selector, family in (
            ("#serif", "Liberation Serif"),
            ("#sans", "Liberation Sans"),
            ("#mono", "Liberation Mono"),
            ("#system", "Liberation Sans"),
            ("#pre", "Liberation Mono"),
            ("#code", "Liberation Mono"),
            ("#explicit", "Liberation Mono"),
        ):
            families = await _platform_families(page, selector)
            assert family in families, f"{selector} used {families}, expected {family}"


@pytest.mark.usefixtures("los_angeles_process_timezone")
async def test_the_page_timezone_is_utc_whatever_the_process_timezone(playwright: Playwright) -> None:
    async with deterministic_browser_context(
        playwright, viewport={"width": 800, "height": 600}, frozen_now_ms=0
    ) as context:
        page = await context.new_page()
        # July, when Los Angeles is 420 minutes behind UTC.
        timezone = await page.evaluate(
            "[Intl.DateTimeFormat().resolvedOptions().timeZone, new Date(2025, 6, 1).getTimezoneOffset()]"
        )

    assert timezone == ["UTC", 0]


async def test_animations_and_transitions_are_pinned_by_the_css(playwright: Playwright) -> None:
    async with deterministic_browser_context(
        playwright, viewport={"width": 800, "height": 600}, frozen_now_ms=0
    ) as context:
        page = await context.new_page()
        await page.set_content(
            f"""
            <style>
              @keyframes pulse {{ to {{ opacity: 0.5; }} }}
              #animated {{ animation: pulse 1s linear infinite; }}
              #transitioned {{ transition: opacity 5s; }}
              {DISABLE_ANIMATIONS_CSS}
            </style>
            <div id="animated">a</div>
            <div id="transitioned">t</div>
            """
        )

        styles = await page.evaluate(
            """() => ({
                playState: getComputedStyle(document.getElementById("animated")).animationPlayState,
                transition: getComputedStyle(document.getElementById("transitioned")).transitionProperty,
            })"""
        )

    assert styles == {"playState": "paused", "transition": "none"}


@pytest.mark.parametrize("fail_in_body", [False, True])
async def test_browser_and_profile_are_cleaned_up(
    playwright: Playwright, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_in_body: bool
) -> None:
    monkeypatch.setenv("TEST_TMPDIR", str(tmp_path))

    pages: list[Page] = []

    async def use_browser() -> None:
        async with deterministic_browser_context(
            playwright, viewport={"width": 800, "height": 600}, frozen_now_ms=0
        ) as context:
            page = await context.new_page()
            pages.append(page)
            assert await asyncio.to_thread(lambda: len(list(tmp_path.glob("chrome-user-data-*")))) == 1
            if fail_in_body:
                raise RuntimeError("test body failed")

    if fail_in_body:
        with pytest.raises(RuntimeError, match="test body failed"):
            await use_browser()
    else:
        await use_browser()
    assert pages
    assert all(page.is_closed() for page in pages)
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("chrome-user-data-*")))


@pytest.mark.parametrize("stage", ["launch", "initialization"])
async def test_failed_browser_setup_removes_profile(
    playwright: Playwright, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    monkeypatch.setenv("TEST_TMPDIR", str(tmp_path))
    context = AsyncMock()
    context.__aenter__.return_value = context
    launch = AsyncMock(return_value=context)
    if stage == "launch":
        launch.side_effect = RuntimeError("setup failed")
    else:
        context.add_init_script.side_effect = RuntimeError("setup failed")
    monkeypatch.setattr(playwright.chromium, "launch_persistent_context", launch)
    with pytest.raises(RuntimeError, match="setup failed"):
        async with deterministic_browser_context(playwright, viewport={"width": 800, "height": 600}, frozen_now_ms=0):
            raise AssertionError("failed setup must not yield a context")
    assert not await asyncio.to_thread(Path(launch.call_args.kwargs["user_data_dir"]).exists)
    if stage == "initialization":
        context.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    pytest_bazel.main()
