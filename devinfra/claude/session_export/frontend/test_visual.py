"""Session viewer behavior and screenshot checkpoints driven by Playwright."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import pytest
import pytest_bazel
from playwright.async_api import Locator, Page, expect

from util.testing.page_capture import wait_for_stable
from util.testing.viewports import Viewport
from util.testing.visual_capture import VisualHarness, VisualPage

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")

_TRANSCRIPT = '[aria-label="Session transcript"] .mantine-ScrollArea-viewport'


@asynccontextmanager
async def _open(visual: VisualHarness, scene: str) -> AsyncIterator[VisualPage]:
    viewport = Viewport(width=420, height=900) if scene.endswith("_mobile") else Viewport()
    scheme: Literal["light", "dark"] = "dark" if scene.endswith("_dark") else "light"
    async with visual.open(scene, viewport=viewport, color_scheme=scheme) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.check(context=scene)
        yield view


async def _capture(view: VisualPage, scene: str) -> None:
    # The old in-page driver never moved the physical pointer onto the controls it activated.
    await view.page.mouse.move(0, 0)
    await view.capture(scene, target=view.page.locator("#app"))


async def _scroll_into_view(target: Locator) -> None:
    await target.evaluate(
        """element => {
            const viewport = document.querySelector('[aria-label="Session transcript"] .mantine-ScrollArea-viewport');
            if (viewport === null) throw new Error('Transcript viewport is missing');
            const targetTop = Math.max(0, (viewport.clientHeight - element.getBoundingClientRect().height) / 2);
            viewport.scrollTop += element.getBoundingClientRect().top - viewport.getBoundingClientRect().top - targetTop;
            viewport.dispatchEvent(new Event('scroll'));
        }"""
    )


async def _click_right_edge(page: Page, button: Locator) -> None:
    await _scroll_into_view(button)
    await wait_for_stable(page)
    geometry = await button.evaluate(
        """button => {
            const rect = button.getBoundingClientRect();
            const parent = button.parentElement.getBoundingClientRect();
            const x = rect.right - 2, y = rect.top + rect.height / 2;
            return { width: rect.width, parentWidth: parent.width, height: rect.height, x, y,
                     clickable: button.contains(document.elementFromPoint(x, y)) };
        }"""
    )
    assert geometry["width"] >= geometry["parentWidth"] - 2, "Disclosure does not fill its row"
    assert geometry["height"] <= 28, "Disclosure exceeds 28px"
    assert geometry["clickable"], "Right edge of disclosure is not clickable"
    await page.mouse.click(geometry["x"], geometry["y"])


async def _noisy_ready(page: Page) -> None:
    await expect(page.locator('[data-message-role="assistant"]').first).to_be_attached()
    await expect(page.locator('[data-fold-kind="notice"]')).to_have_count(0)


@pytest.mark.parametrize(
    "scene",
    [
        "SessionCompletedActivity",
        "SessionCompletedActivityExpanded",
        "SessionCompletedActivity_mobile",
        "SessionCompletedActivityExpanded_mobile",
    ],
)
async def test_completed_activity(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        fixture = await view.page.evaluate("window.__visualFixture__")
        activity = view.page.locator('[data-fold-kind="activity"]').filter(
            has=view.page.locator("summary").filter(has_text=fixture["longCommandActivityTitle"])
        )
        await expect(activity).to_be_attached()
        assert await activity.evaluate("element => element.getBoundingClientRect().height") <= 28
        if "Expanded" in scene:
            await activity.locator("summary").click()
            await expect(activity).to_have_attribute("open", "")
            await expect(activity.locator("[data-activity-title]")).to_have_text(fixture["longCommandActivityTitle"])
            await expect(activity.locator("[data-activity-detail]")).to_have_text(fixture["longCommandActivityDetail"])
            await expect(activity.locator("[data-activity-title]")).to_be_visible()
            await expect(activity.locator("[data-activity-detail]")).to_be_visible()
        await _scroll_into_view(activity)
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionMarkdown", "SessionMarkdown_mobile"])
async def test_markdown_is_sanitized(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        for selector in (
            '[aria-label="Session history"]',
            '[data-message-role="user"] .agentplane-markdown ul',
            '[data-message-role="user"] .agentplane-markdown table',
            '[data-message-role="assistant"] .agentplane-markdown h2',
            '[data-message-role="assistant"] .agentplane-markdown a[href^="https://"]',
            '[data-message-role="assistant"] .agentplane-markdown .agentplane-code-block .cm-editor',
        ):
            await expect(page.locator(selector).first).to_be_attached()
        markdown = page.locator(
            '[data-message-role="user"] .agentplane-markdown, [data-message-role="assistant"] .agentplane-markdown'
        )
        await expect(markdown.locator("script, img, [onclick], [onerror]")).to_have_count(0)
        assert not await markdown.locator("a").evaluate_all(
            "links => links.some(link => /^(javascript|data):/i.test(link.getAttribute('href') ?? ''))"
        )
        assert await page.evaluate("window.__sessionMarkdownFixtureExecuted === undefined")
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionNarrationVisibility", "SessionNarrationVisibility_mobile"])
async def test_narration_is_visible(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        narration = view.page.locator('[data-fold-kind="narration"]')
        await expect(narration).to_be_visible()
        await _scroll_into_view(narration)
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionLatestFirstTail", "SessionLatestFirstAnchor"])
async def test_history_tail_and_prepend_anchor(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        await page.wait_for_function(
            """() => {
                const viewport = document.querySelector('[aria-label="Session transcript"] .mantine-ScrollArea-viewport');
                const latest = document.querySelector('[data-history-sequences~="17"]');
                if (!viewport || !latest || viewport.scrollHeight <= viewport.clientHeight) return false;
                const box = viewport.getBoundingClientRect(), card = latest.getBoundingClientRect();
                return Math.abs(viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight) <= 1
                    && card.bottom > box.top && card.top < box.bottom;
            }"""
        )
        if scene == "SessionLatestFirstAnchor":
            thinking = page.locator('details[aria-label="Thinking"]')
            await expect(thinking).to_be_attached()
            await thinking.evaluate(
                """element => {
                    const viewport = document.querySelector('[aria-label="Session transcript"] .mantine-ScrollArea-viewport');
                    viewport.scrollTop += element.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 100;
                    viewport.dispatchEvent(new Event('scroll'));
                }"""
            )
            await thinking.locator("summary").click()
            await wait_for_stable(page)
            original = await thinking.element_handle()
            top = await thinking.evaluate("element => element.getBoundingClientRect().top")
            # Loading older history must not scroll the reader to the off-screen load control.
            await page.get_by_role("button", name="Load older events").dispatch_event("click")
            await expect(page.locator('[data-history-sequences~="1"]').first).to_be_attached()
            await wait_for_stable(page)
            assert await thinking.evaluate("(element, original) => element === original", original)
            await expect(thinking).to_have_attribute("open", "")
            await expect(page.get_by_role("button", name="Load older events")).to_have_count(0)
            assert abs(await thinking.evaluate("element => element.getBoundingClientRect().top") - top) <= 1.5
        await _capture(view, scene)


@pytest.mark.parametrize(
    "scene",
    [
        "SessionNoisy",
        "SessionNoisy_mobile",
        "SessionNoisyThinking",
        "SessionNoisyRaw",
        "SessionNoisyHook",
        "SessionNoisyHook_mobile",
    ],
)
async def test_noisy_history(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        await expect(page.locator('[data-message-role="assistant"]').first).to_be_attached()
        if "Raw" in scene or "Hook" in scene:
            await page.get_by_role("button", name="Show raw event stream").click()
            rows = page.locator("[data-raw-event]")
            await expect(rows.first).to_be_attached()
            if "Hook" in scene:
                await page.get_by_label("Event kind").select_option("system · hook_response")
                await expect(rows.first).to_be_attached()
                await expect(rows.filter(has_not_text="hook_response")).to_have_count(0)
                await rows.first.locator("summary").click()
                await _scroll_into_view(rows.first)
                await expect(page.locator("[data-event-json]")).to_be_attached()
            else:
                await expect(rows).to_have_count(await page.evaluate("window.__visualFixture__.noisyEventCount"))
                await page.locator(_TRANSCRIPT).evaluate("element => { element.scrollTop = 0; }")
        else:
            await _noisy_ready(page)
            if "Thinking" in scene:
                await page.locator('[data-tool-group-toggle][aria-expanded="false"]').first.click()
                thinking = page.locator('[data-fold-kind="thinking"]').first
                await thinking.locator("summary").click()
                await _scroll_into_view(thinking)
        await _capture(view, scene)


@pytest.mark.parametrize(
    "scene",
    ["SessionNoisySidebar", "SessionNoisySidebarCollapsed", "SessionNoisySidebarWide", "SessionNoisySidebar_mobile"],
)
async def test_sidebar_states(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        await _noisy_ready(page)
        if scene.endswith("_mobile"):
            await page.locator('button[aria-controls="session-sidebar-mobile"]').press("Enter")
            await expect(page.locator(".mantine-Drawer-root #session-sidebar-mobile")).to_be_visible()
            await expect(page.locator(".mantine-Drawer-content")).to_have_css("opacity", "1")
            await page.wait_for_function(
                "() => document.querySelector('.mantine-Drawer-root').getAnimations({ subtree: true }).length === 0"
            )
            await expect(page.locator(".mantine-Drawer-close")).to_be_focused()
        elif "Collapsed" in scene:
            toggle = page.locator('button[aria-controls="session-sidebar"]')
            await toggle.click()
            await expect(toggle).to_have_attribute("aria-expanded", "false")
        elif "Wide" in scene:
            separator = page.locator("[data-session-sidebar-resizer]")
            await separator.press("End")
            maximum = await separator.get_attribute("aria-valuemax")
            assert maximum is not None
            await expect(separator).to_have_attribute("aria-valuenow", maximum)
            # Capture the resized layout, not the keyboard focus outline on its drag handle.
            await separator.blur()
        else:
            await expect(page.locator('button[aria-controls="session-sidebar"]')).to_have_attribute(
                "aria-expanded", "true"
            )
        await _capture(view, scene)


@pytest.mark.parametrize(
    "scene",
    [
        "SessionNoisyTimeline",
        "SessionNoisyTimeline_mobile",
        "SessionNoisyTimelineExpanded",
        "SessionNoisyTimelineExpanded_mobile",
    ],
)
async def test_event_timeline(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        await _noisy_ready(page)
        strips = page.locator("[data-event-strip]")
        await expect(strips.first).to_be_attached()
        sequences = await strips.evaluate_all(
            "strips => strips.flatMap(strip => strip.dataset.historySequences.split(' '))"
        )
        assert len(sequences) == len(set(sequences)) == await page.evaluate("window.__visualFixture__.noisyEventCount")
        for strip in await strips.all():
            assert await strip.evaluate("element => element.getBoundingClientRect().height") <= 28
            assert await strip.locator("[data-event-dot]").count() <= 12
            assert await strip.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
        await expect(page.locator("[data-event-json]")).to_have_count(0)
        assert await page.locator('[data-fold-kind="tool-run"]').count() <= 3
        if "Expanded" in scene:
            await strips.first.locator("[data-event-dot]").first.click()
            await strips.first.locator("[data-raw-event] summary").first.click()
            await expect(strips.first.locator("[data-event-json]")).to_be_attached()
        await _scroll_into_view(strips.first)
        await _capture(view, scene)


@pytest.mark.parametrize(
    "scene", ["SessionNoisyActivity", "SessionNoisyActivityExpanded", "SessionNoisyActivityExpanded_mobile"]
)
async def test_activity_disclosures(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        page = view.page
        await _noisy_ready(page)
        group = page.locator('[data-fold-kind="tool-group"]').first
        await expect(group).to_be_attached()
        assert await group.evaluate("element => element.getBoundingClientRect().height") <= 28
        await expect(group.locator('[data-fold-kind="tool-run"]')).to_have_count(0)
        if "Expanded" in scene:
            await _click_right_edge(page, group.locator("[data-tool-group-toggle]"))
            await _click_right_edge(page, group.locator("[data-tool-run-toggle]").first)
            await expect(group.locator("[data-tool-file-preview]")).to_be_attached()
        await _scroll_into_view(group)
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionViewer", "SessionViewer_dark", "SessionViewer_mobile"])
async def test_session_viewer(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="tool-run"][data-tool-count="5"]')).to_be_attached()
        await expect(view.page.locator("[data-tool-run-toggle]").first).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionToolResult", "SessionToolResult_mobile"])
async def test_session_tool_result(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await view.page.locator("[data-tool-run-toggle]").first.click()
        await _scroll_into_view(view.page.locator('[data-fold-kind="tool-run"]').first)
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(view.page.locator('[data-tool-name="Read"]')).to_be_attached()
        await expect(view.page.locator("[data-tool-output-image]")).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionReadFileResult", "SessionReadFileResult_mobile"])
async def test_session_read_file_result(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await view.page.locator("[data-tool-run-toggle]").first.click()
        await _scroll_into_view(view.page.locator('[data-fold-kind="tool-run"]').first)
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(view.page.locator('[data-tool-file-path="src/session-viewer.ts"]')).to_be_attached()
        await expect(view.page.locator("[data-tool-file-preview]")).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionSubagent", "SessionSubagent_mobile"])
async def test_session_subagent(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await view.page.locator("[data-tool-run-toggle]").first.click()
        await _scroll_into_view(view.page.locator('[data-fold-kind="tool-run"]').first)
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(view.page.locator('[data-subagent-activity][data-subagent-tool-count="2"]')).to_be_attached()
        await expect(view.page.locator('[data-subagent-latest-tool="Grep"]')).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionPeerHold", "SessionPeerHold_mobile"])
async def test_session_peer_hold(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="peer-message"][data-peer-from="plan-agent"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="peer-hold"][data-peer-state="held"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="peer-hold"][data-peer-state="dropped"]')).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionPeerMessage", "SessionPeerMessage_mobile"])
async def test_session_peer_message(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(
            view.page.locator(
                '[data-fold-kind="peer-message"][data-peer-from="review-agent"][data-peer-handback="true"]'
            )
        ).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionLocalCommandRows", "SessionLocalCommandRows_mobile"])
async def test_session_local_command_rows(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await expect(view.page.locator('[aria-label="Session history"]')).to_be_attached()
        await expect(
            view.page.locator('[data-fold-kind="context"][data-context-model="claude-sonnet-4-5"]')
        ).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="stats"][data-stats-state="data"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="usage"]')).to_be_attached()
        await expect(view.page.locator('[data-fold-kind="status"]')).to_be_attached()
        await _capture(view, scene)


@pytest.mark.parametrize("scene", ["SessionSync", "SessionSync_paired_dark", "SessionSync_paired_mobile"])
async def test_session_sync(visual: VisualHarness, scene: str) -> None:
    async with _open(visual, scene) as view:
        await expect(view.page.locator("#overview-heading")).to_be_attached()
        await expect(view.page.locator("#pairing-heading")).to_be_attached()
        await _capture(view, scene)


if __name__ == "__main__":
    pytest_bazel.main()
