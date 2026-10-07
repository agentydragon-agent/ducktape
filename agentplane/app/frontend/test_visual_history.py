"""Agentplane history visual behavior tests."""

import re
from textwrap import dedent
import pytest
from playwright.async_api import expect
from agentplane.app.frontend.visual_pages import capture_scene, open_scene
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness
from agentplane.app.frontend.visual_assertions import _focus, _in_viewport, _open_debug_history, _open_recovery_details, _open_run, _open_tool_run, _rollout_geometry, _rollout_start

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    "scene",
    [
        "realistic_rollout_desktop",
        "realistic_rollout_desktop_dark",
        "realistic_rollout_mobile",
        "reported_rollout_desktop",
    ],
)
async def test_realistic_rollout_overview(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _rollout_start(page)
        await capture_scene(view, scene, output_name=f"{scene.replace('_', '-')}-overview")


@pytest.mark.parametrize(
    "scene",
    [
        "realistic_rollout_desktop",
        "realistic_rollout_desktop_dark",
        "realistic_rollout_mobile",
        "reported_rollout_desktop",
    ],
)
@pytest.mark.parametrize("position", ["start", "end"])
async def test_realistic_rollout_run(scene: str, position: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
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
        await capture_scene(view, scene, output_name=f"{scene.replace('_', '-')}-run-{position}")


@pytest.mark.parametrize("viewport", ["desktop", "mobile"])
@pytest.mark.parametrize("expanded_output", [False, True], ids=["call", "output-scrolled"])
async def test_realistic_rollout_call(viewport: str, expanded_output: bool, visual: VisualHarness) -> None:
    async with open_scene(visual, f"realistic_rollout_{viewport}") as view:
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
            dedent("""element => {
                const heading = element.getBoundingClientRect();
                const divider = getComputedStyle(element, '::after');
                const card = element.closest('.agentplane-collapsible-card').getBoundingClientRect();
                return [heading.left + parseFloat(divider.left) - card.left,
                        card.right - heading.right + parseFloat(divider.right)];
            }""")
        )
        assert all(abs(edge) <= 1 for edge in divider_edges), f"output divider escaped its card: {divider_edges}"
        if expanded_output:
            await _focus(page, output)
            await output.get_by_role("button", name=re.compile(r"^Show all")).click()
            await expect(output).to_have_attribute("data-expanded", "true")
            await output.evaluate(
                dedent("""element => {
                  const history = element.closest('[aria-label="Thread history"]');
                  history.scrollTop += element.getBoundingClientRect().top - history.getBoundingClientRect().top + 300;
                }""")
            )
            await wait_for_stable(page)
            await expect(call.locator(".agentplane-output-label")).to_be_in_viewport()
        else:
            await _focus(page, call.locator(".agentplane-clamped-block[data-label='Command']"))
        await page.mouse.move(0, 0)
        await capture_scene(
            view,
            f"realistic_rollout_{viewport}",
            output_name=f"realistic-rollout-{viewport}-{'output-scrolled' if expanded_output else 'call'}",
        )


@pytest.mark.parametrize(
    "scene",
    ["session_recovery_messages_open", "session_recovery_messages_open_phone", "session_recovery_quiet_open"],
    ids=["messages-desktop", "messages-phone", "quiet-tools"],
)
async def test_recovery_details_open(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_recovery_details(page)
        if scene == "session_recovery_quiet_open":
            await expect(page.locator(".agentplane-step-details .agentplane-code-block").first).to_be_visible()
        else:
            await expect(page.locator('[aria-label="Not retained in context"]')).to_be_visible()
            await expect(page.locator('[aria-label="Retention unknown"]')).to_be_visible()
            await expect(page.locator(".agentplane-disclosure-summary[aria-expanded='true']").first).to_be_visible()
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    "scene",
    [
        "session_error_raw",
        "session_error_raw_phone",
        "session_interleaved_raw",
        "session_interleaved_raw_phone",
        "session_raw",
        "session_raw_phone",
        "session_pending_raw",
    ],
)
async def test_debug_history_latest(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_debug_history(page)
        await expect(
            page.locator('[aria-label="Chronological observations"] [data-debug-observation]').first
        ).to_be_visible()
        if scene == "session_pending_raw":
            await expect(page.locator('[data-thread-anchor="16"]')).to_be_visible()
            await expect(page.locator('.agentplane-user-bubble[data-message-phase="local"]')).to_be_visible()
        await capture_scene(view, scene)


async def test_debug_history_stderr_disclosure(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_interleaved_disclosures") as view:
        page = view.page
        await _open_debug_history(page)
        stderr = page.locator('[data-debug-observation="31"] .agentplane-disclosure-summary')
        await stderr.click()
        await expect(stderr).to_have_attribute("aria-expanded", "true")
        await capture_scene(view, "session_interleaved_disclosures")


async def test_thread_setup_output(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_thread_setup_open") as view:
        page = view.page
        setup = page.locator(".agentplane-disclosure-summary").filter(has_text="Thread setup complete")
        await setup.click()
        await expect(setup).to_have_attribute("aria-expanded", "true")
        await expect(page.get_by_text("Setup stdout")).to_be_visible()
        await capture_scene(view, "session_thread_setup_open")


@pytest.mark.parametrize("scene", ["session_recovery_tools_open", "session_recovery_tools_open_phone"])
async def test_recovery_tool_lower_states(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_recovery_details(page)
        await _in_viewport(page.get_by_text("Failed, still in context", exact=True))
        await _focus(page, page.locator('[aria-label="Retention unknown"]').last)
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["session_recovery_tools_open", "session_recovery_tools_open_phone"])
async def test_revised_recovery_tool_output(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_recovery_details(page)
        output = page.locator(".agentplane-output-label").filter(has_text="Continuation output")
        await _focus(page, output)
        await _in_viewport(page.get_by_text("aborted", exact=True))
        await capture_scene(view, scene, output_name=f"{scene}_revised")


@pytest.mark.parametrize("scene", ["session_reasoning", "session_reasoning_phone"], ids=["desktop", "phone"])
async def test_reasoning_inside_tool_run(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_run(page)
        reasoning = page.locator(".agentplane-step-details").filter(
            has=page.locator(".agentplane-step-title:text-is('Reasoning')")
        )
        await reasoning.locator(".agentplane-disclosure-summary").first.click()
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    "scene", ["session_reasoning_sticky", "session_reasoning_sticky_phone"], ids=["desktop", "phone"]
)
async def test_reasoning_heading_sticks_at_history_bottom(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
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
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    "scene",
    [
        "session_standalone_reasoning_open",
        "session_reasoning_code_fence_open",
        "session_reasoning_code_fence_open_phone",
    ],
    ids=["standalone", "fence-desktop", "fence-phone"],
)
async def test_standalone_reasoning_opens(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        reasoning = page.locator('[data-thread-anchor="20"] .agentplane-step-details')
        summary = reasoning.locator(".agentplane-disclosure-summary")
        await summary.click()
        await expect(summary).to_have_attribute("aria-expanded", "true")
        await expect(reasoning.locator(".agentplane-disclosure-panel .agentplane-markdown")).to_be_visible()
        if "code_fence" in scene:
            await expect(reasoning.locator(".agentplane-code-block .cm-content")).to_be_attached()
        else:
            await expect(reasoning.locator('a[href="https://example.test/projection"]')).to_have_text("projection path")
        await capture_scene(view, scene)


@pytest.mark.parametrize("scene", ["session_shell_calls", "session_shell_calls_phone"], ids=["desktop", "phone"])
async def test_shell_call_run_previews(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_run(page)
        await expect(page.locator(".agentplane-step-details .agentplane-step-preview").first).to_be_visible()
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    ("scene", "anchor"), [("session_evidence", "4"), ("session_evidence_phone", "34")], ids=["desktop", "phone"]
)
async def test_thread_evidence_panel(scene: str, anchor: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
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
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    ("scene", "target"),
    [
        ("session_evidence_hover_bubble", '[data-thread-anchor="4"] .agentplane-user-bubble'),
        ("session_evidence_hover_reply", '[data-thread-anchor="34"] .agentplane-evidence-owner'),
    ],
    ids=["bubble", "reply"],
)
async def test_evidence_button_reveals_on_hover(scene: str, target: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        owner = page.locator(target)
        await owner.hover()
        await expect(owner.get_by_role("button", name="Evidence")).to_have_css("opacity", "1")
        await capture_scene(view, scene)


async def test_evidence_button_reveals_on_tap(visual: VisualHarness) -> None:
    async with open_scene(visual, "session_evidence_tap_phone") as view:
        page = view.page
        owner = page.locator('[data-thread-anchor="34"] .agentplane-evidence-owner')
        await owner.tap()
        await expect(owner).to_have_attribute("data-evidence-revealed", "")
        await capture_scene(view, "session_evidence_tap_phone")


@pytest.mark.parametrize(
    ("scene", "shell_calls"),
    [
        ("session_tool_payloads", False),
        ("session_tool_payloads_phone", False),
        ("session_shell_calls_open", True),
        ("session_shell_calls_open_phone", True),
    ],
    ids=["tool-desktop", "tool-phone", "shell-desktop", "shell-phone"],
)
async def test_open_tool_calls_and_output(scene: str, shell_calls: bool, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_tool_run(page)
        await expect(
            page.locator(".agentplane-output-disclosure .agentplane-disclosure-summary[aria-expanded='true']").first
        ).to_be_attached()
        if shell_calls:
            await expect(page.locator("[data-clamped='true']").first).to_be_attached()
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    ("scene", "call_text", "tool", "suffix"),
    [
        ("session_shell_calls_open", "List every container and its status", "Bash", "claude"),
        ("session_shell_calls_open_phone", "List every container and its status", "Bash", "claude"),
        ("session_shell_calls_open", "Test Bank", "Shell", "codex"),
        ("session_shell_calls_open_phone", "Test Bank", "Shell", "codex"),
    ],
    ids=["claude-desktop", "claude-phone", "codex-desktop", "codex-phone"],
)
async def test_shell_call_command_and_output(
    scene: str, call_text: str, tool: str, suffix: str, visual: VisualHarness
) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_tool_run(page)
        call = page.locator(".agentplane-step-details").filter(has_text=call_text)
        await expect(call.locator(".agentplane-step-title")).to_have_text(tool)
        await _focus(page, call.locator(".agentplane-clamped-block[data-label='Command']"))
        await _in_viewport(call.locator(".agentplane-output-label"))
        await capture_scene(view, scene, output_name=f"{scene}_{suffix}")


@pytest.mark.parametrize("scene", ["session_compact_run", "session_compact_run_phone"], ids=["desktop", "phone"])
async def test_collapsed_steps_in_open_run_are_compact(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
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
        await capture_scene(view, scene)


@pytest.mark.parametrize(
    "scene", ["session_tool_output_sticky", "session_tool_output_sticky_phone"], ids=["desktop", "phone"]
)
async def test_expanded_command_uses_heading_to_collapse(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        await _open_tool_run(page)
        command = (
            page.locator(".agentplane-clamped-block[data-label='Command']")
            .filter(has=page.get_by_role("button", name=re.compile(r"^Show all")))
            .first
        )
        await expect(command).to_be_attached()
        await command.get_by_role("button", name=re.compile(r"^Show all")).click()
        # The Show all control disappears after expansion, so use the expanded
        # block rather than a locator that keeps filtering for Show all.
        heading = page.locator(
            ".agentplane-clamped-block[data-label='Command'][data-expanded='true'] "
            ".agentplane-clamped-disclosure .agentplane-disclosure-heading"
        ).first
        await expect(heading.locator("button")).to_have_count(1)
        await expect(heading.get_by_role("button", name="Command", expanded=True)).to_be_visible()
        await _focus(page, heading)
        await capture_scene(view, scene, output_name=f"{scene}_expanded_command")


@pytest.mark.parametrize(
    "scene", ["session_tool_output_sticky", "session_tool_output_sticky_phone"], ids=["desktop", "phone"]
)
async def test_expanded_shell_output_sticks_while_scrolling(scene: str, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
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
        await capture_scene(view, scene)
