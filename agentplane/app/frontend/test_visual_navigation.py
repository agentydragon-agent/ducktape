"""Agentplane navigation visual behavior tests."""
from util.testing.viewports import DESKTOP, MOBILE, SMALL_MOBILE, Viewport
import re
import pytest
import pytest_bazel
from playwright.async_api import expect
from agentplane.app.frontend.visual_assertions import _assert_phone_composer_layout
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness
pytestmark = pytest.mark.asyncio(loop_scope='session')

async def test_archived_thread_toggle(visual: VisualHarness) -> None:
    async with visual.open('threads', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.locator('.agentplane-sidebar-archived-toggle label').click()
        await expect(page.get_by_role('switch', name='Show archived threads')).to_be_checked()
        await expect(page.locator('.agentplane-thread-status-indicator[data-status="archived"]')).to_be_visible()
        await page.mouse.move(0, 0)
        await expect(page.get_by_role('tooltip')).to_have_count(0)
        await view.capture('threads_archived', target=view.page.locator('#app'))

async def test_mobile_navigation_drawer_threads_phone_drawer(visual: VisualHarness) -> None:
    async with visual.open('threads', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Toggle navigation').click()
        await expect(page.locator('.agentplane-sidebar-open')).to_be_visible()
        await expect(page.locator('a.agentplane-sidebar-group-name').first).to_be_visible()
        await view.capture('threads-phone-drawer', target=view.page.locator('#app'))

async def test_mobile_navigation_drawer_threads_failed_turn_phone_drawer(visual: VisualHarness) -> None:
    async with visual.open('threads_failed_turn', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Toggle navigation').click()
        await expect(page.locator('.agentplane-sidebar-open')).to_be_visible()
        await expect(page.locator('.agentplane-thread-status-indicator[data-status="turn_error"]').first).to_be_visible()
        await view.capture('threads-failed-turn-phone-drawer', target=view.page.locator('#app'))

async def test_mobile_navigation_drawer_threads_provisioning_phone(visual: VisualHarness) -> None:
    async with visual.open('threads_provisioning', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Toggle navigation').click()
        await expect(page.locator('.agentplane-sidebar-open')).to_be_visible()
        await expect(page.locator('a[href="#/sandboxes/test-provisioning"]').first).to_be_visible()
        await view.capture('threads_provisioning_phone', target=view.page.locator('#app'))

async def test_mobile_navigation_drawer_threads_disconnected_phone(visual: VisualHarness) -> None:
    async with visual.open('threads_disconnected', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Toggle navigation').click()
        await expect(page.locator('.agentplane-sidebar-open')).to_be_visible()
        await expect(page.locator('[data-connection="degraded"]').first).to_be_visible()
        await view.capture('threads_disconnected_phone', target=view.page.locator('#app'))

async def test_mobile_drawer_covers_thread_controls(visual: VisualHarness) -> None:
    async with visual.open('session_reasoning_sticky', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        await reasoning.locator('.agentplane-disclosure-summary').first.click()
        history = page.locator("[aria-label='Thread history']")
        await expect(history).to_have_attribute('data-layout-settled', 'true')
        await history.evaluate('element => { element.scrollTop = element.scrollHeight / 2; }')
        await wait_for_stable(page)
        await page.get_by_role('button', name='Toggle navigation').click()
        drawer = page.locator('.agentplane-sidebar-open')
        await expect(drawer).to_be_visible()
        # A sticky disclosure heading (z=100) or Jump to latest (z=101) in the main
        # column must never punch through the drawer's lower numeric z-index.
        assert await page.evaluate("() => {\n            const drawer = document.querySelector('.agentplane-sidebar-open');\n            const main = document.querySelector('.agentplane-shell-main');\n            if (!drawer || !main) return false;\n            return getComputedStyle(main).zIndex === '0' &&\n                getComputedStyle(drawer).zIndex === '30' &&\n                document.elementFromPoint(innerWidth / 2, innerHeight / 2)?.closest('.agentplane-sidebar') === drawer;\n        }")
        await view.capture('session-phone-drawer-over-transcript', target=view.page.locator('#app'))

async def test_mobile_drawer_covers_jump_to_latest(visual: VisualHarness) -> None:
    async with visual.open('session_streaming_interleaved', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state='attached')
        await view.check(context='fixture ready')
        page = view.page
        history = page.locator("[aria-label='Thread history']")
        await expect(history).to_have_attribute('data-layout-settled', 'true')
        # The fixture's folded run is short; open it to create real scroll distance
        # before the reader leaves the bottom of this still-running thread.
        await history.locator('.agentplane-disclosure-summary').filter(has_text='32 tool calls').first.click()
        await history.hover()
        await page.mouse.wheel(0, -2500)
        jump = page.get_by_role('button', name='Jump to latest')
        await expect(jump).to_be_visible()
        point = await jump.bounding_box()
        assert point is not None
        await page.get_by_role('button', name='Toggle navigation').click()
        await expect(page.locator('.agentplane-sidebar-open')).to_be_visible()
        # Probe where the actual high-z floating button was painted, not an arbitrary
        # uncovered patch of the drawer.
        assert await page.evaluate("point => {\n            const top = document.elementFromPoint(point.x + point.width / 2, point.y + point.height / 2);\n            return top?.closest('.agentplane-sidebar-open') === document.querySelector('.agentplane-sidebar-open');\n        }", point)
        await view.capture('session_phone_drawer_over_active_thread')

async def test_disconnected_threads_tooltip(visual: VisualHarness) -> None:
    async with visual.open('threads_disconnected', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        indicator = page.locator('[data-connection][aria-label*="reconnecting"]')
        await indicator.focus()
        await expect(page.get_by_text(re.compile('Threads: reconnecting since'))).to_be_visible()
        await view.capture('threads_disconnected')

async def test_paused_claude_harness_choice_sandboxes_claude_paused(visual: VisualHarness) -> None:
    async with visual.open('sandboxes_claude_paused', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('[role="option"][data-combobox-disabled]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        harness = page.get_by_role('combobox', name='Harness')
        await expect(harness).to_have_value('Codex')
        await harness.click()
        await expect(page.locator('[role="option"][data-combobox-disabled]')).to_be_visible()
        await view.capture('sandboxes_claude_paused', target=view.page.locator('#app'))

async def test_paused_claude_harness_choice_sandbox_claude_paused(visual: VisualHarness) -> None:
    async with visual.open('sandbox_claude_paused', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('[role="option"][data-combobox-disabled]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        harness = page.get_by_role('combobox', name='Harness')
        await expect(harness).to_have_value('Codex')
        await harness.click()
        await expect(page.locator('[role="option"][data-combobox-disabled]')).to_be_visible()
        await view.capture('sandbox_claude_paused', target=view.page.locator('#app'))

async def test_phone_composer_controls_fit(visual: VisualHarness) -> None:
    async with visual.open('session', viewport=SMALL_MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _assert_phone_composer_layout(page)
        await view.capture('session_phone_controls')

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'session_more_menu'), (MOBILE, 'session_more_menu_phone')])
async def test_composer_more_menu(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('session', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='More', exact=True).click()
        await expect(page.get_by_role('menuitem', name='Debug history')).to_be_visible()
        await expect(page.get_by_role('menu')).to_be_visible()
        await expect(page.locator('[data-thread-anchor="34"]')).to_be_attached()
        await view.capture(image_name)
if __name__ == '__main__':
    pytest_bazel.main()
