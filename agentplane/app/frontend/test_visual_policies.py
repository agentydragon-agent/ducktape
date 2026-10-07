"""Agentplane policies visual behavior tests."""

import re

import pytest
from playwright.async_api import expect

from agentplane.app.frontend.visual_assertions import (
    _assert_phone_composer_layout,
    _focus,
    _in_viewport,
    _open_raw_switches,
    _open_select,
    _select_reconnect,
)
from agentplane.app.frontend.visual_pages import capture_scene, open_scene
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    "scene",
    ["actions_attention_composer_open_desktop", "actions_attention_composer_open_phone"],
    ids=["desktop", "phone"],
)
async def test_inline_action_review(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await page.get_by_role("button", name="Review pending actions").click()
        await expect(page.get_by_role("button", name="Hide pending action details")).to_be_visible()
        await expect(page.locator(".action-affordance-notice .agentplane-code-block").first).to_be_visible()
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    "scene",
    ["actions_attention_composer_long_desktop", "actions_attention_composer_long_phone"],
    ids=["desktop", "phone"],
)
async def test_inline_action_review_scrolls_to_decisions(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await page.get_by_role("button", name="Review pending actions").click()
        details = page.locator(".action-affordance-details:not([hidden])")
        await expect(details.get_by_role("button", name="Approve").first).to_be_attached()
        await details.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        await wait_for_stable(page)
        assert await details.evaluate("element => element.scrollTop") > 0
        await _in_viewport(details.get_by_role("button", name="Approve").last)
        if scene.endswith("phone"):
            await _assert_phone_composer_layout(page)
        await capture_scene(view, scene)


async def test_actions_raw_switches(visual: VisualHarness) -> None:
    async with open_scene(visual, "actions_raw") as view:
        page = view.page
        await _open_raw_switches(page)
        raw_switches = page.locator("label").filter(has_text=re.compile(r"^Raw$"))
        await _focus(page, raw_switches.last)
        await capture_scene(view, "actions_raw")


@pytest.mark.parametrize("scene", ["sandbox_status_raw", "sandbox_status_raw_phone"], ids=["desktop", "phone"])
async def test_sandbox_status_raw_switches(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_raw_switches(page)
        await expect(page.locator(".agentplane-code-block").first).to_be_visible()
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["connections", "connections_phone"], ids=["desktop", "phone"])
async def test_connections_settings_modal(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        if scene == "connections_phone":
            await page.get_by_role("button", name="Toggle navigation").click()
        await page.get_by_role("button", name="Settings").click()
        await expect(page.locator("[data-connection-id]").first).to_be_visible()
        if scene == "connections_phone":
            await page.mouse.move(0, 0)
        await capture_scene(view, scene)


async def test_consent_reconnect_warning_desktop(visual: VisualHarness) -> None:
    async with open_scene(visual, "consent_reconnect") as view:
        page = view.page
        await _select_reconnect(page)
        await _in_viewport(page.locator("[data-reconnect-review]").get_by_text("Replace authorization", exact=False))
        await capture_scene(view, "consent_reconnect")


@pytest.mark.parametrize("scene", ["actions_history", "actions_history_phone"], ids=["desktop", "phone"])
async def test_action_history_receipt(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        receipt = page.get_by_text("list the test backup archive", exact=True)
        await _focus(page, receipt)
        await _in_viewport(page.get_by_text("History", exact=True))
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["actions_history", "actions_history_phone"], ids=["desktop", "phone"])
async def test_action_history_diagram(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        image = page.locator('img[src^="data:image/"]').first
        await _focus(page, image)
        await _in_viewport(page.get_by_text("render the test diagram", exact=True))
        await capture_scene(view, scene, output_name=f"{scene}_diagram")


async def test_action_history_raw_receipt(visual: VisualHarness) -> None:
    async with open_scene(visual, "actions_history_raw") as view:
        page = view.page
        result = page.get_by_text("Result", exact=True).first
        await _open_raw_switches(page)
        await _focus(page, result)
        await capture_scene(view, "actions_history_raw")


async def test_action_history_paging_control(visual: VisualHarness) -> None:
    async with open_scene(visual, "actions_history_more") as view:
        page = view.page
        load_more = page.get_by_test_id("action-history-load-more")
        await expect(load_more).to_have_text("Load more")
        await page.locator(".agentplane-shell-main").evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        await wait_for_stable(page)
        # The scroll extent can grow after the first move. Bring the control into view after
        # that layout settles, then verify the final captured state.
        await load_more.scroll_into_view_if_needed()
        await wait_for_stable(page)
        await _in_viewport(load_more)
        await capture_scene(view, "actions_history_more")


@pytest.mark.parametrize("scene", ["mcp_servers", "mcp_servers_phone"], ids=["desktop", "phone"])
async def test_mcp_servers_linked_and_expired(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _in_viewport(page.locator('[data-mcp-server="linkage:example_docs"]').get_by_text("linked", exact=True))
        await _in_viewport(
            page.locator('[data-mcp-server="linkage:example_cluster"]').get_by_text("expired", exact=True)
        )
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    ("scene", "focus_key", "focus_state", "other_key", "other_state", "suffix"),
    [
        ("mcp_servers_phone", "linkage:example_pantry", "unlinked", "linkage:example_calendar", "degraded", "oauth"),
        ("mcp_servers", "group:example_notes", "available", "group:example_mail", "connect_failed", "health"),
        ("mcp_servers_phone", "group:example_notes", "available", "group:example_mail", "connect_failed", "health"),
    ],
    ids=["oauth-phone", "health-desktop", "health-phone"],
)
async def test_mcp_servers_lower_statuses(
    scene: str, focus_key: str, focus_state: str, other_key: str, other_state: str, suffix: str, visual: VisualHarness
) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        focused = page.locator(f'[data-mcp-server="{focus_key}"]').get_by_text(focus_state, exact=True)
        await _focus(page, focused)
        await _in_viewport(page.locator(f'[data-mcp-server="{other_key}"]').get_by_text(other_state, exact=True))
        if scene == "mcp_servers":
            # All lower states fit together at desktop width, so one focused image covers them.
            await _in_viewport(
                page.locator('[data-mcp-server="linkage:example_calendar"]').get_by_text("degraded", exact=True)
            )
            await _in_viewport(
                page.locator('[data-mcp-server="linkage:example_pantry"]').get_by_text("unlinked", exact=True)
            )
        await capture_scene(view, scene, output_name=f"{scene}_{suffix}")


async def test_consent_reconnect_warning_phone(visual: VisualHarness) -> None:
    async with open_scene(visual, "consent_reconnect_phone") as view:
        page = view.page
        await _select_reconnect(page)
        await _in_viewport(page.locator("[data-reconnect-review]").get_by_text("Replace authorization", exact=False))
        await _in_viewport(page.get_by_text(re.compile("I confirm replacing this Connection")))
        await capture_scene(view, "consent_reconnect_phone")


async def test_consent_reconnect_decision_phone(visual: VisualHarness) -> None:
    async with open_scene(visual, "consent_reconnect_phone") as view:
        page = view.page
        await _select_reconnect(page)
        authorize = page.get_by_role("button", name="Authorize")
        await _focus(page, authorize)
        await _in_viewport(page.get_by_role("button", name="Deny"))
        await expect(authorize).to_be_disabled()
        await capture_scene(view, "consent_reconnect_phone", output_name="consent_reconnect_phone_decision")


@pytest.mark.parametrize("scene", ["new_sandbox", "new_sandbox_phone"], ids=["desktop", "phone"])
async def test_action_policy_selector_hides_picked_option(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_select(page, label="Action policy sets", available="harness-reviews", picked="public-coder")
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["new_sandbox_policies", "new_sandbox_policies_phone"], ids=["desktop", "phone"])
async def test_egress_policy_selector_hides_picked_option(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_select(
            page, label="Egress policies", available="pypi", picked="github-public", press_arrow_down=True
        )
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["new_sandbox_grants", "new_sandbox_grants_phone"], ids=["desktop", "phone"])
async def test_grant_selector_hides_picked_option(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_select(page, label="Kubernetes grants", available="config-read", picked="workspace-read")
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["sandbox_egress", "sandbox_egress_phone"], ids=["desktop", "phone"])
async def test_sandbox_egress_pick_updates_options(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_select(page, label="Grant egress policies", available="pypi")
        await page.get_by_role("option", name=re.compile("pypi")).click()
        await expect(page.locator(".mantine-Pill-root", has_text="pypi")).to_be_visible()
        await expect(page.get_by_role("option", name=re.compile("github-public"))).to_be_visible()
        await expect(page.get_by_role("option", name=re.compile("pypi"))).to_have_count(0)
        await page.mouse.move(0, 0)
        await expect(page.get_by_role("tooltip")).to_have_count(0)
        await wait_for_stable(page)
        await capture_scene(view, scene)
