"""Agentplane policies visual behavior tests."""
from util.testing.viewports import DESKTOP, MOBILE, Viewport
import re
import pytest
import pytest_bazel
from playwright.async_api import expect
from agentplane.app.frontend.visual_assertions import _assert_phone_composer_layout, _focus, _in_viewport, _open_raw_switches, _open_select, _select_reconnect
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness
pytestmark = pytest.mark.asyncio(loop_scope='session')

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'actions_attention_composer_open_desktop'), (MOBILE, 'actions_attention_composer_open_phone')])
async def test_inline_action_review(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('actions_attention_composer', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Review pending actions').click()
        await expect(page.get_by_role('button', name='Hide pending action details')).to_be_visible()
        await expect(page.locator('.action-affordance-notice .agentplane-code-block').first).to_be_visible()
        await view.capture(image_name)

async def test_inline_action_review_scrolls_to_decisions_actions_attention_composer_long_desktop(visual: VisualHarness) -> None:
    async with visual.open('actions_attention_composer_long', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Review pending actions').click()
        details = page.locator('.action-affordance-details:not([hidden])')
        await expect(details.get_by_role('button', name='Approve').first).to_be_attached()
        await details.evaluate('element => { element.scrollTop = element.scrollHeight; }')
        await wait_for_stable(page)
        assert await details.evaluate('element => element.scrollTop') > 0
        await _in_viewport(details.get_by_role('button', name='Approve').last)
        await view.capture('actions_attention_composer_long_desktop')

async def test_inline_action_review_scrolls_to_decisions_actions_attention_composer_long_phone(visual: VisualHarness) -> None:
    async with visual.open('actions_attention_composer_long', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Review pending actions').click()
        details = page.locator('.action-affordance-details:not([hidden])')
        await expect(details.get_by_role('button', name='Approve').first).to_be_attached()
        await details.evaluate('element => { element.scrollTop = element.scrollHeight; }')
        await wait_for_stable(page)
        assert await details.evaluate('element => element.scrollTop') > 0
        await _in_viewport(details.get_by_role('button', name='Approve').last)
        await _assert_phone_composer_layout(page)
        await view.capture('actions_attention_composer_long_phone')

async def test_actions_raw_switches(visual: VisualHarness) -> None:
    async with visual.open('actions', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _open_raw_switches(page)
        raw_switches = page.locator('label').filter(has_text=re.compile('^Raw$'))
        await _focus(page, raw_switches.last)
        await view.capture('actions_raw', target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'sandbox-status-raw'), (MOBILE, 'sandbox-status-raw-phone')])
async def test_sandbox_status_raw_switches(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('sandbox_status', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _open_raw_switches(page)
        await expect(page.locator('.agentplane-code-block').first).to_be_visible()
        await view.capture(image_name, target=view.page.locator('#app'))

async def test_connections_settings_modal_connections(visual: VisualHarness) -> None:
    async with visual.open('threads', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Settings').click()
        await expect(page.locator('[data-connection-id]').first).to_be_visible()
        await view.capture('connections', target=view.page.locator('#app'))

async def test_connections_settings_modal_connections_phone(visual: VisualHarness) -> None:
    async with visual.open('threads', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await page.get_by_role('button', name='Toggle navigation').click()
        await page.get_by_role('button', name='Settings').click()
        await expect(page.locator('[data-connection-id]').first).to_be_visible()
        await page.mouse.move(0, 0)
        await view.capture('connections_phone', target=view.page.locator('#app'))

async def test_consent_reconnect_warning_desktop(visual: VisualHarness) -> None:
    async with visual.open('consent', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _select_reconnect(page)
        await _in_viewport(page.locator('[data-reconnect-review]').get_by_text('Replace authorization', exact=False))
        await view.capture('consent_reconnect', target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'actions_history'), (MOBILE, 'actions_history_phone')])
async def test_action_history_receipt(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('actions', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.agentplane-disclosure-summary', state='attached')
        await view.page.wait_for_selector('img[src^="data:image/"]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        receipt = page.get_by_text('list the test backup archive', exact=True)
        await _focus(page, receipt)
        await _in_viewport(page.get_by_text('History', exact=True))
        await view.capture(image_name, target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'actions_history_diagram'), (MOBILE, 'actions_history_phone_diagram')])
async def test_action_history_diagram(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('actions', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.agentplane-disclosure-summary', state='attached')
        await view.page.wait_for_selector('img[src^="data:image/"]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        image = page.locator('img[src^="data:image/"]').first
        await _focus(page, image)
        await _in_viewport(page.get_by_text('render the test diagram', exact=True))
        await view.capture(image_name, target=view.page.locator('#app'))

async def test_action_history_raw_receipt(visual: VisualHarness) -> None:
    async with visual.open('actions', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        result = page.get_by_text('Result', exact=True).first
        await _open_raw_switches(page)
        await _focus(page, result)
        await view.capture('actions_history_raw', target=view.page.locator('#app'))

async def test_action_history_paging_control(visual: VisualHarness) -> None:
    async with visual.open('actions_history_more', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.agentplane-disclosure-summary', state='attached')
        await view.page.wait_for_selector('[data-testid="action-history-load-more"]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        load_more = page.get_by_test_id('action-history-load-more')
        await expect(load_more).to_have_text('Load more')
        await page.locator('.agentplane-shell-main').evaluate('element => { element.scrollTop = element.scrollHeight; }')
        await wait_for_stable(page)
        # The scroll extent can grow after the first move. Bring the control into view after
        # that layout settles, then verify the final captured state.
        await load_more.scroll_into_view_if_needed()
        await wait_for_stable(page)
        await _in_viewport(load_more)
        await view.capture('actions_history_more', target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'mcp_servers'), (MOBILE, 'mcp_servers_phone')])
async def test_mcp_servers_linked_and_expired(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('mcp_servers', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('[data-mcp-server]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        await _in_viewport(page.locator('[data-mcp-server="linkage:example_docs"]').get_by_text('linked', exact=True))
        await _in_viewport(page.locator('[data-mcp-server="linkage:example_cluster"]').get_by_text('expired', exact=True))
        await view.capture(image_name, target=view.page.locator('#app'))

@pytest.mark.parametrize(('focus_key', 'focus_state', 'other_key', 'other_state', 'image_name'), [('linkage:example_pantry', 'unlinked', 'linkage:example_calendar', 'degraded', 'mcp_servers_phone_oauth'), ('group:example_notes', 'available', 'group:example_mail', 'connect_failed', 'mcp_servers_phone_health')])
async def test_mcp_servers_lower_statuses_mcp_servers_phone(visual: VisualHarness, focus_key: str, focus_state: str, other_key: str, other_state: str, image_name: str) -> None:
    async with visual.open('mcp_servers', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('[data-mcp-server]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        focused = page.locator(f'[data-mcp-server="{focus_key}"]').get_by_text(focus_state, exact=True)
        await _focus(page, focused)
        await _in_viewport(page.locator(f'[data-mcp-server="{other_key}"]').get_by_text(other_state, exact=True))
        await view.capture(image_name, target=view.page.locator('#app'))

async def test_mcp_servers_lower_statuses_mcp_servers(visual: VisualHarness) -> None:
    async with visual.open('mcp_servers', viewport=DESKTOP) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('[data-mcp-server]', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        focused = page.locator('[data-mcp-server="group:example_notes"]').get_by_text('available', exact=True)
        await _focus(page, focused)
        await _in_viewport(page.locator('[data-mcp-server="group:example_mail"]').get_by_text('connect_failed', exact=True))
        # All lower states fit together at desktop width, so one focused image covers them.
        await _in_viewport(page.locator('[data-mcp-server="linkage:example_calendar"]').get_by_text('degraded', exact=True))
        await _in_viewport(page.locator('[data-mcp-server="linkage:example_pantry"]').get_by_text('unlinked', exact=True))
        await view.capture('mcp_servers_health', target=view.page.locator('#app'))

async def test_consent_reconnect_warning_phone(visual: VisualHarness) -> None:
    async with visual.open('consent', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _select_reconnect(page)
        await _in_viewport(page.locator('[data-reconnect-review]').get_by_text('Replace authorization', exact=False))
        await _in_viewport(page.get_by_text(re.compile('I confirm replacing this Connection')))
        await view.capture('consent_reconnect_phone', target=view.page.locator('#app'))

async def test_consent_reconnect_decision_phone(visual: VisualHarness) -> None:
    async with visual.open('consent', viewport=MOBILE) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _select_reconnect(page)
        authorize = page.get_by_role('button', name='Authorize')
        await _focus(page, authorize)
        await _in_viewport(page.get_by_role('button', name='Deny'))
        await expect(authorize).to_be_disabled()
        await view.capture('consent_reconnect_phone_decision', target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'new-sandbox'), (MOBILE, 'new-sandbox-phone')])
async def test_action_policy_selector_hides_picked_option(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('new_sandbox', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.mantine-Pill-root', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        await _open_select(page, label='Action policy sets', available='harness-reviews', picked='public-coder')
        await view.capture(image_name, target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'new-sandbox-policies'), (MOBILE, 'new-sandbox-policies-phone')])
async def test_egress_policy_selector_hides_picked_option(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('new_sandbox', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.mantine-Pill-root:has-text("github-public")', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        await _open_select(page, label='Egress policies', available='pypi', picked='github-public', press_arrow_down=True)
        await view.capture(image_name, target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'new-sandbox-grants'), (MOBILE, 'new-sandbox-grants-phone')])
async def test_grant_selector_hides_picked_option(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('new_sandbox', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.page.wait_for_selector('.mantine-Pill-root', state='attached')
        await view.check(context='fixture ready')
        page = view.page
        await _open_select(page, label='Kubernetes grants', available='config-read', picked='workspace-read')
        await view.capture(image_name, target=view.page.locator('#app'))

@pytest.mark.parametrize(('screen', 'image_name'), [(DESKTOP, 'sandbox-egress'), (MOBILE, 'sandbox-egress-phone')])
async def test_sandbox_egress_pick_updates_options(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open('sandbox_egress', viewport=screen) as view:
        await expect(view.page.locator('#app > *').first).to_be_attached()
        await view.check(context='fixture ready')
        page = view.page
        await _open_select(page, label='Grant egress policies', available='pypi')
        await page.get_by_role('option', name=re.compile('pypi')).click()
        await expect(page.locator('.mantine-Pill-root', has_text='pypi')).to_be_visible()
        await expect(page.get_by_role('option', name=re.compile('github-public'))).to_be_visible()
        await expect(page.get_by_role('option', name=re.compile('pypi'))).to_have_count(0)
        await page.mouse.move(0, 0)
        await expect(page.get_by_role('tooltip')).to_have_count(0)
        await wait_for_stable(page)
        await view.capture(image_name, target=view.page.locator('#app'))
if __name__ == '__main__':
    pytest_bazel.main()
