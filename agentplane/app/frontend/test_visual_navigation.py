"""Agentplane navigation visual behavior tests."""

import re
import pytest
from playwright.async_api import expect
from agentplane.app.frontend.visual_pages import capture_scene, open_scene
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness
from agentplane.app.frontend.visual_assertions import _assert_phone_composer_layout

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_archived_thread_toggle(visual: VisualHarness) -> None:
    async with open_scene(visual, "threads_archived") as view:
        page = view.page
        await page.locator(".agentplane-sidebar-archived-toggle label").click()
        await expect(page.get_by_role("switch", name="Show archived threads")).to_be_checked()
        await expect(page.locator('.agentplane-thread-status-indicator[data-status="archived"]')).to_be_visible()
        await page.mouse.move(0, 0)
        await expect(page.get_by_role("tooltip")).to_have_count(0)
        await capture_scene(view, "threads_archived")


@pytest.mark.parametrize(
    ("scene", "after_open"),
    [
        ("threads_phone_drawer", "a.agentplane-sidebar-group-name"),
        ("threads_failed_turn_phone_drawer", '.agentplane-thread-status-indicator[data-status="turn_error"]'),
        ("threads_provisioning_phone", 'a[href="#/sandboxes/test-provisioning"]'),
        ("threads_disconnected_phone", '[data-connection="degraded"]'),
    ],
    ids=["normal", "failed-turn", "provisioning", "disconnected"],
)
async def test_mobile_navigation_drawer(scene: str, after_open: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await page.get_by_role("button", name="Toggle navigation").click()
        await expect(page.locator(".agentplane-sidebar-open")).to_be_visible()
        await expect(page.locator(after_open).first).to_be_visible()
        await capture_scene(view, scene)


async def test_mobile_drawer_covers_thread_controls(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_reasoning_sticky_phone") as view:
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        await reasoning.locator(".agentplane-disclosure-summary").first.click()
        history = page.locator("[aria-label='Thread history']")
        await expect(history).to_have_attribute("data-layout-settled", "true")
        await history.evaluate("element => { element.scrollTop = element.scrollHeight / 2; }")
        await wait_for_stable(page)
        await page.get_by_role("button", name="Toggle navigation").click()
        drawer = page.locator(".agentplane-sidebar-open")
        await expect(drawer).to_be_visible()
        # A sticky disclosure heading (z=100) or Jump to latest (z=101) in the main
        # column must never punch through the drawer's lower numeric z-index.
        assert await page.evaluate("""() => {
            const drawer = document.querySelector('.agentplane-sidebar-open');
            const main = document.querySelector('.agentplane-shell-main');
            if (!drawer || !main) return false;
            return getComputedStyle(main).zIndex === '0' &&
                getComputedStyle(drawer).zIndex === '30' &&
                document.elementFromPoint(innerWidth / 2, innerHeight / 2)?.closest('.agentplane-sidebar') === drawer;
        }""")
        await capture_scene(view, "session_reasoning_sticky_phone", output_name="session-phone-drawer-over-transcript")


async def test_mobile_drawer_covers_jump_to_latest(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_phone_drawer_over_active_thread") as view:
        page = view.page
        history = page.locator("[aria-label='Thread history']")
        await expect(history).to_have_attribute("data-layout-settled", "true")
        # The fixture's folded run is short; open it to create real scroll distance
        # before the reader leaves the bottom of this still-running thread.
        await history.locator(".agentplane-disclosure-summary").filter(has_text="32 tool calls").first.click()
        await history.hover()
        await page.mouse.wheel(0, -2500)
        jump = page.get_by_role("button", name="Jump to latest")
        await expect(jump).to_be_visible()
        point = await jump.bounding_box()
        assert point is not None
        await page.get_by_role("button", name="Toggle navigation").click()
        await expect(page.locator(".agentplane-sidebar-open")).to_be_visible()
        # Probe where the actual high-z floating button was painted, not an arbitrary
        # uncovered patch of the drawer.
        assert await page.evaluate(
            """point => {
            const top = document.elementFromPoint(point.x + point.width / 2, point.y + point.height / 2);
            return top?.closest('.agentplane-sidebar-open') === document.querySelector('.agentplane-sidebar-open');
        }""",
            point,
        )
        await capture_scene(view, "session_phone_drawer_over_active_thread")


async def test_disconnected_threads_tooltip(visual: VisualHarness) -> None:
    async with open_scene(visual, "threads_disconnected") as view:
        page = view.page
        indicator = page.locator('[data-connection][aria-label*="reconnecting"]')
        await indicator.focus()
        await expect(page.get_by_text(re.compile("Threads: reconnecting since"))).to_be_visible()
        await capture_scene(view, "threads_disconnected")


@pytest.mark.parametrize("scene", ["sandboxes_claude_paused", "sandbox_claude_paused"], ids=["list", "detail"])
async def test_paused_claude_harness_choice(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        harness = page.get_by_role("combobox", name="Harness")
        await expect(harness).to_have_value("Codex")
        await harness.click()
        await expect(page.locator('[role="option"][data-combobox-disabled]')).to_be_visible()
        await capture_scene(view, scene)


async def test_phone_composer_controls_fit(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_phone_controls") as view:
        page = view.page
        await _assert_phone_composer_layout(page)
        await capture_scene(view, "session_phone_controls")


@pytest.mark.parametrize("scene", ["session_more_menu", "session_more_menu_phone"], ids=["desktop", "phone"])
async def test_composer_more_menu(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await page.get_by_role("button", name="More", exact=True).click()
        await expect(page.get_by_role("menuitem", name="Debug history")).to_be_visible()
        await expect(page.get_by_role("menu")).to_be_visible()
        await expect(page.locator('[data-thread-anchor="34"]')).to_be_attached()
        await capture_scene(view, scene)
