"""Haku shell renders and interactions, driven through Playwright."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import pytest
import pytest_bazel
from playwright.async_api import expect

from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness, VisualPage
from util.testing.viewports import Viewport

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.parametrize("color_scheme", ["light", "dark"])]


@asynccontextmanager
async def _scene(
    visual: VisualHarness, name: str, color_scheme: Literal["light", "dark"], *, width: int, height: int
) -> AsyncIterator[VisualPage]:
    async with visual.open(
        name,
        viewport=Viewport(width=width, height=height, device_scale_factor=2),
        color_scheme=color_scheme,
        window_globals={"__SCENE__": name, "__COLOR_SCHEME__": color_scheme},
    ) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context=name)
        yield view


async def _close_approvals(view: VisualPage) -> None:
    await view.page.locator(".haku-shell-drawer [aria-label='Close approvals']").click()
    await view.page.wait_for_selector(".haku-shell-drawer", state="hidden")
    await _park_pointer(view)


async def _park_pointer(view: VisualPage) -> None:
    await view.check(context="interaction")
    await view.page.mouse.move(0, 0)
    await wait_for_stable(view.page)


async def _capture(view: VisualPage, name: str, color_scheme: str) -> None:
    # Approval controls arm asynchronously; page-specific tests wait for their own content.
    for selector in (
        "button:has-text('Approve'):disabled",
        "button:has-text('Deny'):disabled",
        "[aria-label='Loading MCP servers']",
        "[aria-label='Loading Agents']",
        "[aria-label='Loading Agent enrollment']",
        "[aria-label='Checking connection status']",
    ):
        await view.page.wait_for_selector(selector, state="hidden")
    await view.capture(f"{name}-{color_scheme}", label=f"{name} - {color_scheme}")


async def test_console(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "console", color_scheme, width=1200, height=800) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "console", color_scheme)


async def test_console_drawer(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "console-drawer", color_scheme, width=1200, height=800) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "console-drawer", color_scheme)


async def test_console_mobile(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "console-mobile", color_scheme, width=390, height=760) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "console-mobile", color_scheme)


async def test_not_found(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "not-found", color_scheme, width=900, height=600) as view:
        await view.page.wait_for_selector(":text('Page not found')", state="attached")
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "not-found", color_scheme)


async def test_approvals_embed(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "approvals-embed", color_scheme, width=560, height=820) as view:
        await view.page.wait_for_selector("button:has-text('Approve')", state="attached")
        await _capture(view, "approvals-embed", color_scheme)


async def test_settings(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings", color_scheme)


async def test_settings_mobile(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-mobile", color_scheme, width=390, height=760) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-mobile", color_scheme)


async def test_settings_agents(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-agents", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('Agents')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('Agents')", state="visible")
        await view.page.wait_for_selector(":text('Public Coder')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-agents", color_scheme)


async def test_settings_grants(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-grants", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('Grants')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('Grants')", state="visible")
        await view.page.wait_for_selector(":text('Public Coder')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-grants", color_scheme)


async def test_settings_grants_history(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-grants-history", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('Grants')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('Grants')", state="visible")
        await _park_pointer(view)
        await view.page.locator(":text('History')").click()
        await view.page.wait_for_selector(":text('Pilot complete; return to standard diagnostics.')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-grants-history", color_scheme)


async def test_settings_grants_revoke(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-grants-revoke", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('Grants')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('Grants')", state="visible")
        await _park_pointer(view)
        await view.page.locator("button:has-text('Revoke') >> nth=0").click()
        await view.page.wait_for_selector(":text('Confirm')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-grants-revoke", color_scheme)


async def test_settings_notifications(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-notifications", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('Notifications')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('Notifications')", state="visible")
        await view.page.wait_for_selector(":text('This browser')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-notifications", color_scheme)


async def test_settings_system(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "settings-system", color_scheme, width=1200, height=1000) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[role='tab']:has-text('System')").click()
        await view.page.wait_for_selector("[role='tab'][aria-selected='true']:has-text('System')", state="visible")
        await view.page.wait_for_selector(":text('Mixed revisions')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "settings-system", color_scheme)


async def test_agent_enrollment(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "agent-enrollment", color_scheme, width=1200, height=900) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "agent-enrollment", color_scheme)


async def test_agent_enrollment_reconnect(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "agent-enrollment-reconnect", color_scheme, width=1200, height=900) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "agent-enrollment-reconnect", color_scheme)


async def test_agent_enrollment_mobile(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "agent-enrollment-mobile", color_scheme, width=390, height=760) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "agent-enrollment-mobile", color_scheme)


async def test_history(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "history", color_scheme, width=1200, height=1500) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[aria-label='Full'] >> nth=0").click()
        await view.page.wait_for_selector("summary:has-text('Metadata')", state="visible")
        await _park_pointer(view)
        await view.page.locator("summary:has-text('Metadata')").click()
        await view.page.wait_for_selector(".haku-shell-disclosure[open] .haku-shell-disclosure-body", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "history", color_scheme)


async def test_history_auto_approved(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "history-auto-approved", color_scheme, width=1200, height=1500) as view:
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.locator("[aria-label='Show auto-approved']").click()
        await view.page.wait_for_selector(":text('Auto-approved by unconditional_v1')", state="visible")
        await _park_pointer(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await _capture(view, "history-auto-approved", color_scheme)


async def test_history_paged(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "history-paged", color_scheme, width=1200, height=900) as view:
        await view.page.wait_for_selector("button:has-text('Load older calls')", state="attached")
        await expect(view.page.frame_locator("iframe[src^='https://haku-ui.test/']").locator("main")).to_be_attached()
        await _close_approvals(view)
        await view.page.wait_for_selector("[aria-label='Syncing']", state="hidden")
        await view.page.locator(".haku-page-scroll").evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        await _capture(view, "history-paged", color_scheme)


async def test_sync_current(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "sync-current", color_scheme, width=600, height=420) as view:
        await view.page.locator("[aria-label='Up to date']").click()
        await view.page.wait_for_selector("[aria-label='Sync status']", state="visible")
        await _park_pointer(view)
        await _capture(view, "sync-current", color_scheme)


async def test_sync_syncing(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "sync-syncing", color_scheme, width=600, height=420) as view:
        await view.page.locator("[aria-label='Syncing']").click()
        await view.page.wait_for_selector("[aria-label='Sync status']", state="visible")
        await _park_pointer(view)
        await _capture(view, "sync-syncing", color_scheme)


async def test_sync_error(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "sync-error", color_scheme, width=600, height=420) as view:
        await view.page.locator("[aria-label='Sync error']").click()
        await view.page.wait_for_selector("[aria-label='Sync status']", state="visible")
        await _park_pointer(view)
        await _capture(view, "sync-error", color_scheme)


async def test_session_expiring(visual: VisualHarness, color_scheme: Literal["light", "dark"]) -> None:
    async with _scene(visual, "session-expiring", color_scheme, width=600, height=420) as view:
        await view.page.locator("[aria-label='Session expiring soon']").click()
        await view.page.wait_for_selector("[aria-label='Console session']", state="visible")
        await _park_pointer(view)
        await _capture(view, "session-expiring", color_scheme)


if __name__ == "__main__":
    pytest_bazel.main()
