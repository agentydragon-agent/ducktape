"""Agentplane history visual behavior tests."""

import re
from textwrap import dedent

import pytest
import pytest_bazel
from playwright.async_api import expect

from agentplane.app.frontend.visual_app import IDLE_THREAD, RUNNING_THREAD, AgentplaneFixture
from agentplane.app.frontend.visual_assertions import (
    _focus,
    _in_viewport,
    _open_debug_history,
    _open_recovery_details,
    _open_run,
    _open_tool_run,
    _rollout_geometry,
    _rollout_start,
)
from util.testing.page_capture import wait_for_stable
from util.testing.viewports import DESKTOP, MOBILE, MOBILE_TOUCH, Viewport
from util.testing.visual_capture import VisualHarness

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "realistic-rollout-desktop-overview"), (MOBILE, "realistic-rollout-mobile-overview")],
)
async def test_realistic_rollout_overview_realistic_rollout_desktop(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.completed_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await view.capture(image_name)


async def test_realistic_rollout_overview_realistic_rollout_desktop_dark(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP, color_scheme="dark") as view:
        app = AgentplaneFixture(view.page)
        await app.completed_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await view.capture("realistic-rollout-desktop-dark-overview")


async def test_realistic_rollout_overview_reported_rollout_desktop(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.reported_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await view.capture("reported-rollout-desktop-overview")


@pytest.mark.parametrize(
    ("position", "screen", "image_name"),
    [
        ("start", DESKTOP, "realistic-rollout-desktop-run-start"),
        ("start", MOBILE, "realistic-rollout-mobile-run-start"),
        ("end", DESKTOP, "realistic-rollout-desktop-run-end"),
        ("end", MOBILE, "realistic-rollout-mobile-run-end"),
    ],
)
async def test_realistic_rollout_run_realistic_rollout_desktop(
    visual: VisualHarness, position: str, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.completed_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await _open_run(page)
        steps = page.locator(".agentplane-run-steps").first
        if position == "start":
            static_title = await steps.locator(".agentplane-step-static .agentplane-step-title").first.bounding_box()
            disclosure_title = await steps.locator(
                ".agentplane-step-details .agentplane-step-title"
            ).first.bounding_box()
            assert static_title is not None
            assert disclosure_title is not None
            assert abs(static_title["x"] - disclosure_title["x"]) <= 1, "plain and expandable steps must align"
        target = steps.locator(":scope > *").first if position == "start" else steps.locator(":scope > *").last
        await _focus(page, target)
        await target.hover()
        await _rollout_geometry(page, f"run-{position}")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("position", "image_name"),
    [("start", "realistic-rollout-desktop-dark-run-start"), ("end", "realistic-rollout-desktop-dark-run-end")],
)
async def test_realistic_rollout_run_realistic_rollout_desktop_dark(
    visual: VisualHarness, position: str, image_name: str
) -> None:
    async with visual.open(viewport=DESKTOP, color_scheme="dark") as view:
        app = AgentplaneFixture(view.page)
        await app.completed_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await _open_run(page)
        steps = page.locator(".agentplane-run-steps").first
        if position == "start":
            static_title = await steps.locator(".agentplane-step-static .agentplane-step-title").first.bounding_box()
            disclosure_title = await steps.locator(
                ".agentplane-step-details .agentplane-step-title"
            ).first.bounding_box()
            assert static_title is not None
            assert disclosure_title is not None
            assert abs(static_title["x"] - disclosure_title["x"]) <= 1, "plain and expandable steps must align"
        target = steps.locator(":scope > *").first if position == "start" else steps.locator(":scope > *").last
        await _focus(page, target)
        await target.hover()
        await _rollout_geometry(page, f"run-{position}")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("position", "image_name"),
    [("start", "reported-rollout-desktop-run-start"), ("end", "reported-rollout-desktop-run-end")],
)
async def test_realistic_rollout_run_reported_rollout_desktop(
    visual: VisualHarness, position: str, image_name: str
) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.reported_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await _open_run(page)
        steps = page.locator(".agentplane-run-steps").first
        if position == "start":
            static_title = await steps.locator(".agentplane-step-static .agentplane-step-title").first.bounding_box()
            disclosure_title = await steps.locator(
                ".agentplane-step-details .agentplane-step-title"
            ).first.bounding_box()
            assert static_title is not None
            assert disclosure_title is not None
            assert abs(static_title["x"] - disclosure_title["x"]) <= 1, "plain and expandable steps must align"
        target = steps.locator(":scope > *").first if position == "start" else steps.locator(":scope > *").last
        await _focus(page, target)
        await target.hover()
        await _rollout_geometry(page, f"run-{position}")
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("expanded_output", "screen", "image_name"),
    [
        (False, DESKTOP, "realistic-rollout-desktop-call"),
        (False, MOBILE, "realistic-rollout-mobile-call"),
        (True, DESKTOP, "realistic-rollout-desktop-output-scrolled"),
        (True, MOBILE, "realistic-rollout-mobile-output-scrolled"),
    ],
)
async def test_realistic_rollout_call(
    visual: VisualHarness, expanded_output: bool, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.completed_rollout()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector("[aria-label='Thread history'][data-layout-settled='true']", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _rollout_start(page)
        await _open_run(page)
        call = (
            page.locator(".agentplane-run-steps .agentplane-step-details")
            .filter(has=page.locator(".agentplane-step-title:text-is('Shell')"))
            .nth(1)
        )
        await call.locator(".agentplane-disclosure-summary").first.click()
        output = call.locator(".agentplane-clamped-block[data-label='Output']")
        await expect(output).to_be_attached()
        heading = call.locator(
            ".agentplane-output-disclosure > .agentplane-disclosure-item > .agentplane-disclosure-heading"
        )
        divider_edges = await heading.evaluate(
            dedent(
                "element => {\n                const heading = element.getBoundingClientRect();\n                const divider = getComputedStyle(element, '::after');\n                const card = element.closest('.agentplane-collapsible-card').getBoundingClientRect();\n                return [heading.left + parseFloat(divider.left) - card.left,\n                        card.right - heading.right + parseFloat(divider.right)];\n            }"
            )
        )
        assert all(abs(edge) <= 1 for edge in divider_edges), f"output divider escaped its card: {divider_edges}"
        if expanded_output:
            await _focus(page, output)
            await output.get_by_role("button", name=re.compile("^Show all")).click()
            await expect(output).to_have_attribute("data-expanded", "true")
            await output.evaluate(
                dedent(
                    "element => {\n                  const history = element.closest('[aria-label=\"Thread history\"]');\n                  history.scrollTop += element.getBoundingClientRect().top - history.getBoundingClientRect().top + 300;\n                }"
                )
            )
            await wait_for_stable(page)
            await expect(call.locator(".agentplane-output-label")).to_be_in_viewport()
        else:
            await _focus(page, call.locator(".agentplane-clamped-block[data-label='Command']"))
        await page.mouse.move(0, 0)
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "session_recovery_messages_open"), (MOBILE, "session_recovery_messages_open_phone")],
)
async def test_recovery_details_open_session_recovery_messages_open(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("messages")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_recovery_details(page)
        await expect(page.locator('[aria-label="Not retained in context"]')).to_be_visible()
        await expect(page.locator('[aria-label="Retention unknown"]')).to_be_visible()
        await expect(page.locator(".agentplane-disclosure-summary[aria-expanded='true']").first).to_be_visible()
        await view.capture(image_name)


async def test_recovery_details_open_session_recovery_quiet_open(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("quiet")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_recovery_details(page)
        await expect(page.locator(".agentplane-step-details .agentplane-code-block").first).to_be_visible()
        await view.capture("session_recovery_quiet_open")


async def test_debug_history_latest_session_error_raw(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.failed_turn(after_content=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        await view.capture("session_error_raw")


async def test_debug_history_latest_session_error_raw_phone(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE) as view:
        app = AgentplaneFixture(view.page)
        await app.failed_turn(after_content=False)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        await view.capture("session_error_raw_phone")


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_interleaved_raw"), (MOBILE, "session_interleaved_raw_phone")]
)
async def test_debug_history_latest_session_interleaved_raw(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.interleaved_events()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        await view.capture(image_name)


@pytest.mark.parametrize(("screen", "image_name"), [(DESKTOP, "session_raw"), (MOBILE, "session-raw-phone")])
async def test_debug_history_latest_session_raw(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_debug_history_latest_session_pending_raw(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.pending_commands()
        await app.remember_pending_input()
        await app.mount_thread(RUNNING_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        await expect(page.locator('[data-thread-anchor="16"]')).to_be_visible()
        await expect(page.locator('.agentplane-user-bubble[data-message-phase="local"]')).to_be_visible()
        await view.capture("session_pending_raw")


async def test_debug_history_stderr_disclosure(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.interleaved_events()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_debug_history(page)
        stderr = page.locator('[data-debug-observation="31"] .agentplane-disclosure-summary')
        await stderr.click()
        await expect(stderr).to_have_attribute("aria-expanded", "true")
        await view.capture("session_interleaved_disclosures")


async def test_thread_setup_output(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.thread_setup()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        setup = page.locator(".agentplane-disclosure-summary").filter(has_text="Thread setup complete")
        await setup.click()
        await expect(setup).to_have_attribute("aria-expanded", "true")
        await expect(page.get_by_text("Setup stdout")).to_be_visible()
        await view.capture("session_thread_setup_open")


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_recovery_tools_open"), (MOBILE, "session_recovery_tools_open_phone")]
)
async def test_recovery_tool_lower_states(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("tools")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_recovery_details(page)
        await _in_viewport(page.get_by_text("Failed, still in context", exact=True))
        await _focus(page, page.locator('[aria-label="Retention unknown"]').last)
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "session_recovery_tools_open_revised"), (MOBILE, "session_recovery_tools_open_phone_revised")],
)
async def test_revised_recovery_tool_output(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.recovery("tools")
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_recovery_details(page)
        output = page.locator(".agentplane-output-label").filter(has_text="Continuation output")
        await _focus(page, output)
        await _in_viewport(page.get_by_text("aborted", exact=True))
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-reasoning"), (MOBILE, "session-reasoning-phone")]
)
async def test_reasoning_inside_tool_run(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.standard_history(long_preview=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_run(page)
        reasoning = page.locator(".agentplane-step-details").filter(
            has=page.locator(".agentplane-step-title:text-is('Reasoning')")
        )
        await reasoning.locator(".agentplane-disclosure-summary").first.click()
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-reasoning-sticky"), (MOBILE, "session-reasoning-sticky-phone")]
)
async def test_reasoning_heading_sticks_at_history_bottom(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning(long_body=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        await reasoning.locator(".agentplane-disclosure-summary").first.click()
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        history = page.locator("[aria-label='Thread history']")
        await expect(history).to_have_attribute("data-layout-settled", "true")
        await history.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        await wait_for_stable(page)
        await expect(reasoning.locator(".agentplane-disclosure-summary").first).to_have_attribute(
            "aria-expanded", "true"
        )
        await view.capture(image_name, target=view.page.locator("#app"))


async def test_standalone_reasoning_opens_session_standalone_reasoning_open(visual: VisualHarness) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning(long_preview=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        summary = reasoning.locator(".agentplane-disclosure-summary")
        await summary.click()
        await expect(summary).to_have_attribute("aria-expanded", "true")
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        await expect(reasoning.locator('a[href="https://example.test/projection"]')).to_have_text("projection path")
        await view.capture("session-standalone-reasoning-open", target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [(DESKTOP, "session-reasoning-code-fence-open"), (MOBILE, "session-reasoning-code-fence-open-phone")],
)
async def test_standalone_reasoning_opens_session_reasoning_code_fence_open(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.standalone_reasoning(code_fence=True)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        summary = reasoning.locator(".agentplane-disclosure-summary")
        await summary.click()
        await expect(summary).to_have_attribute("aria-expanded", "true")
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        await expect(reasoning.locator(".agentplane-code-block .cm-content")).to_be_attached()
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-shell-calls"), (MOBILE, "session-shell-calls-phone")]
)
async def test_shell_call_run_previews(visual: VisualHarness, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        await _open_run(page)
        await expect(page.locator(".agentplane-step-details .agentplane-step-preview").first).to_be_visible()
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("anchor", "screen", "image_name"), [("4", DESKTOP, "session_evidence"), ("34", MOBILE, "session_evidence_phone")]
)
async def test_thread_evidence_panel(visual: VisualHarness, anchor: str, screen: Viewport, image_name: str) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        owner = page.locator(f'[data-thread-anchor="{anchor}"]')
        button = owner.locator("button.agentplane-evidence-toggle").first
        # The overlay button is reachable by keyboard even when another row covers its corner.
        await button.focus()
        await button.press("Enter")
        await expect(button).to_have_attribute("aria-expanded", "true")
        await expect(owner.locator("[data-evidence-observation]").first).to_be_visible()
        await button.blur()
        await page.mouse.move(0, 0)
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("target", "image_name"),
    [
        ('[data-thread-anchor="4"] .agentplane-user-bubble', "session_evidence_hover_bubble"),
        ('[data-thread-anchor="34"] .agentplane-evidence-owner', "session_evidence_hover_reply"),
    ],
)
async def test_evidence_button_reveals_on_hover(visual: VisualHarness, target: str, image_name: str) -> None:
    async with visual.open(viewport=DESKTOP) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        owner = page.locator(target)
        await owner.hover()
        await expect(owner.get_by_role("button", name="Evidence")).to_have_css("opacity", "1")
        await view.capture(image_name)


async def test_evidence_button_reveals_on_tap(visual: VisualHarness) -> None:
    async with visual.open(viewport=MOBILE_TOUCH) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context="fixture ready")
        page = view.page
        owner = page.locator('[data-thread-anchor="34"] .agentplane-evidence-owner')
        await owner.tap()
        await expect(owner).to_have_attribute("data-evidence-revealed", "")
        await view.capture("session_evidence_tap_phone")


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-tool-payloads"), (MOBILE, "session-tool-payloads-phone")]
)
async def test_open_tool_calls_and_output_session_tool_payloads(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_tool_run(page)
        await expect(
            page.locator(".agentplane-output-disclosure .agentplane-disclosure-summary[aria-expanded='true']").first
        ).to_be_attached()
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-shell-calls-open"), (MOBILE, "session-shell-calls-open-phone")]
)
async def test_open_tool_calls_and_output_session_shell_calls_open(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_tool_run(page)
        await expect(
            page.locator(".agentplane-output-disclosure .agentplane-disclosure-summary[aria-expanded='true']").first
        ).to_be_attached()
        await expect(page.locator("[data-clamped='true']").first).to_be_attached()
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("call_text", "tool", "screen", "image_name"),
    [
        ("List every container and its status", "Bash", DESKTOP, "session_shell_calls_open_claude"),
        ("List every container and its status", "Bash", MOBILE, "session_shell_calls_open_phone_claude"),
        ("Test Bank", "Shell", DESKTOP, "session_shell_calls_open_codex"),
        ("Test Bank", "Shell", MOBILE, "session_shell_calls_open_phone_codex"),
    ],
)
async def test_shell_call_command_and_output(
    visual: VisualHarness, call_text: str, tool: str, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_tool_run(page)
        call = page.locator(".agentplane-step-details").filter(has_text=call_text)
        await expect(call.locator(".agentplane-step-title")).to_have_text(tool)
        await _focus(page, call.locator(".agentplane-clamped-block[data-label='Command']"))
        await _in_viewport(call.locator(".agentplane-output-label"))
        await view.capture(image_name, target=view.page.locator("#app"))


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session_compact_run"), (MOBILE, "session_compact_run_phone")]
)
async def test_collapsed_steps_in_open_run_are_compact(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_run(page)
        await expect(page.locator(".agentplane-step-details [aria-busy='true']")).to_have_count(0)
        steps = page.locator(
            ".agentplane-run-steps .agentplane-step-details .agentplane-disclosure-summary[aria-expanded='false']"
        )
        await expect(steps.first).to_be_attached()
        # Both kinds share the step disclosure control. Its normal mobile min-height
        # and label padding must not turn every collapsed step into a full-size card.
        assert await steps.first.evaluate("el => getComputedStyle(el).minHeight") == "24px"
        assert (
            await steps.first.locator(".agentplane-disclosure-summary-content").evaluate(
                "el => getComputedStyle(el).paddingBlockStart"
            )
            == "0px"
        )
        await _focus(page, steps.first)
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"),
    [
        (DESKTOP, "session_tool_output_sticky_expanded_command"),
        (MOBILE, "session_tool_output_sticky_phone_expanded_command"),
    ],
)
async def test_expanded_command_uses_heading_to_collapse(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_tool_run(page)
        command = (
            page.locator(".agentplane-clamped-block[data-label='Command']")
            .filter(has=page.get_by_role("button", name=re.compile("^Show all")))
            .first
        )
        await expect(command).to_be_attached()
        await command.get_by_role("button", name=re.compile("^Show all")).click()
        # The Show all control disappears after expansion, so use the expanded
        # block rather than a locator that keeps filtering for Show all.
        heading = page.locator(
            ".agentplane-clamped-block[data-label='Command'][data-expanded='true'] .agentplane-clamped-disclosure .agentplane-disclosure-heading"
        ).first
        await expect(heading.locator("button")).to_have_count(1)
        await expect(heading.get_by_role("button", name="Command", expanded=True)).to_be_visible()
        await _focus(page, heading)
        await view.capture(image_name)


@pytest.mark.parametrize(
    ("screen", "image_name"), [(DESKTOP, "session-tool-output-sticky"), (MOBILE, "session-tool-output-sticky-phone")]
)
async def test_expanded_shell_output_sticks_while_scrolling(
    visual: VisualHarness, screen: Viewport, image_name: str
) -> None:
    async with visual.open(viewport=screen) as view:
        app = AgentplaneFixture(view.page)
        await app.shell_calls()
        await app.mount_thread(IDLE_THREAD)
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector(".agentplane-disclosure-summary", state="attached")
        await view.check(context="fixture ready")
        page = view.page
        await _open_tool_run(page)
        output = page.locator(".agentplane-output-disclosure .agentplane-disclosure-summary[aria-expanded='true']")
        await expect(output.first).to_be_attached()
        # The long Codex command and output are present before enumerating expansion controls.
        await expect(page.locator(".agentplane-clamped-block[data-label='Command']").first).to_be_attached()
        await expect(page.locator(".agentplane-clamped-block[data-label='Arguments']").first).to_be_attached()
        await expect(page.locator(".agentplane-clamped-block[data-label='Output']").first).to_be_attached()
        await expect(page.locator(".agentplane-step-details [aria-busy='true']")).to_have_count(0)
        await expect(page.locator("[aria-label='Thread history'][data-layout-settled='true']")).to_be_attached()
        controls = page.locator(".agentplane-clamped-block button[aria-expanded='false']")
        count = await controls.count()
        assert count > 0, "long command/output had no expansion controls"
        for _ in range(count):
            await controls.first.click()
            await wait_for_stable(page)
        await expect(controls).to_have_count(0)
        await expect(page.locator("[aria-label='Thread history'][data-layout-settled='true']")).to_be_attached()
        await page.locator("[aria-label='Thread history']").evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        await wait_for_stable(page)
        await view.capture(image_name)


if __name__ == "__main__":
    pytest_bazel.main()
