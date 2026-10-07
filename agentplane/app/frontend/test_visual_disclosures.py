"""Agentplane disclosures visual behavior tests."""

import pytest
from playwright.async_api import expect
from agentplane.app.frontend.visual_pages import capture_scene, open_scene
from util.testing.page_capture import wait_for_stable
from util.testing.visual_capture import VisualHarness
from agentplane.app.frontend.visual_assertions import _INNER, _MAIN, _OUTER, _OUTPUT, _SCROLL, _box, _expect_at, _expect_released, _focus, _heading_top, _height, _in_viewport, _open_tool_run, _scroll_to, _scroll_to_copy

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_collapsed_disclosure(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_collapsed") as view:
        page = view.page
        await expect(page.locator(_MAIN)).to_have_attribute("data-expanded", "false")
        assert await page.locator(_SCROLL).evaluate("element => element.scrollTop") == 0
        await capture_scene(view, "disclosure_component_phone_collapsed")


async def test_short_disclosure_fits(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_short_expanded") as view:
        page = view.page
        assert not await page.locator(_SCROLL).evaluate("element => element.scrollHeight > element.clientHeight")
        await expect(page.locator(_MAIN)).to_have_attribute("data-expanded", "true")
        await capture_scene(view, "disclosure_component_phone_short_expanded")


async def test_long_disclosure_before_sticking(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_long_top") as view:
        page = view.page
        assert await page.locator(_SCROLL).evaluate("element => element.scrollHeight > element.clientHeight")
        assert await page.locator(_SCROLL).evaluate("element => element.scrollTop") == 0
        top = await _heading_top(page, _MAIN)
        viewport = await _box(page, _SCROLL)
        assert 0 < top < viewport["height"] * 0.6
        await capture_scene(view, "disclosure_component_phone_long_top")


async def test_long_disclosure_sticks(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_long_scrolled") as view:
        page = view.page
        await _scroll_to_copy(page, "long-paragraph", 64)
        await _expect_at(page, _MAIN, 0)
        await capture_scene(view, "disclosure_component_phone_long_scrolled")


async def test_disclosure_releases_after_content(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_after_disclosure") as view:
        page = view.page
        await _scroll_to_copy(page, "following-disclosure", 64)
        await _expect_released(page, _MAIN)
        await capture_scene(view, "disclosure_component_phone_after_disclosure")


async def test_nested_parent_sticks_before_child(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_parent_only") as view:
        page = view.page
        outer_height = await _height(page, _OUTER)
        await _scroll_to_copy(page, "outer-paragraph", outer_height + 8)
        await _expect_at(page, _OUTER, 0)
        inner_top = await _heading_top(page, _INNER)
        viewport = await _box(page, _SCROLL)
        assert outer_height + 4 < inner_top < viewport["height"]
        await capture_scene(view, "disclosure_component_phone_nested_parent_only")


@pytest.mark.parametrize(
    ("scene", "wrapped"),
    [
        ("disclosure_component_phone_nested_child_scrolled", False),
        ("disclosure_component_phone_nested_wrapped_headings", True),
    ],
    ids=["plain", "wrapped"],
)
async def test_nested_headings_stack(scene: str, wrapped: bool, visual: VisualHarness) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        outer_height = await _height(page, _OUTER)
        inner_height = await _height(page, _INNER)
        await _scroll_to_copy(page, "nested-paragraph", outer_height + inner_height + 16)
        await _expect_at(page, _OUTER, 0)
        await _expect_at(page, _INNER, outer_height)
        if wrapped:
            assert outer_height >= 56, "outer mobile heading did not wrap"
            assert inner_height >= 56, "inner mobile heading did not wrap"
        await capture_scene(view, scene)


async def test_nested_child_releases_behind_parent(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_after_child") as view:
        page = view.page
        outer_height = await _height(page, _OUTER)
        await _scroll_to_copy(page, "following-nested", outer_height + 16)
        await _expect_at(page, _OUTER, 0)
        outer_box, inner_box = await _box(page, _OUTER), await _box(page, _INNER)
        outer_z = int(await page.locator(_OUTER).evaluate("element => getComputedStyle(element).zIndex"))
        inner_z = int(await page.locator(_INNER).evaluate("element => getComputedStyle(element).zIndex"))
        assert inner_box["y"] + inner_box["height"] <= outer_box["y"] + outer_box["height"] + 1
        assert outer_z > inner_z
        await capture_scene(view, "disclosure_component_phone_nested_after_child")


async def test_nested_parent_releases_after_content(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_after_outer") as view:
        page = view.page
        await _scroll_to_copy(page, "following-outer", 64)
        await _expect_released(page, _INNER)
        await _expect_released(page, _OUTER)
        await capture_scene(view, "disclosure_component_phone_nested_after_outer")


async def test_output_heading_stacks_below_tool(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_expanded_output") as view:
        page = view.page
        outer_height, inner_height, output_height = (
            await _height(page, _OUTER),
            await _height(page, _INNER),
            await _height(page, _OUTPUT),
        )
        await _scroll_to_copy(page, "output-paragraph", outer_height + inner_height + output_height + 16)
        await _expect_at(page, _OUTER, 0)
        await _expect_at(page, _INNER, outer_height)
        await _expect_at(page, _OUTPUT, outer_height + inner_height)
        await capture_scene(view, "disclosure_component_phone_nested_expanded_output")


async def test_output_heading_enters_below_tool(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_before_output") as view:
        page = view.page
        outer_height, inner_height = await _height(page, _OUTER), await _height(page, _INNER)
        await _scroll_to_copy(page, "before-output", outer_height + inner_height + 16)
        await _expect_at(page, _OUTER, 0)
        await _expect_at(page, _INNER, outer_height)
        output_top = await _heading_top(page, _OUTPUT)
        viewport = await _box(page, _SCROLL)
        assert outer_height + inner_height + 4 < output_top < viewport["height"]
        await capture_scene(view, "disclosure_component_phone_nested_before_output")


async def test_collapsed_output_keeps_its_sticky_slot(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_output_collapsed") as view:
        page = view.page
        outer_height, inner_height = await _height(page, _OUTER), await _height(page, _INNER)
        await _scroll_to(page, _OUTPUT, outer_height + inner_height)
        await _expect_at(page, _OUTER, 0)
        await _expect_at(page, _INNER, outer_height)
        await _expect_at(page, _OUTPUT, outer_height + inner_height)
        await expect(page.locator(_OUTPUT)).to_have_attribute("data-expanded", "false")
        await capture_scene(view, "disclosure_component_phone_nested_output_collapsed")


async def test_output_heading_releases_after_content(visual: VisualHarness) -> None:
    async with open_scene(visual, "disclosure_component_phone_nested_after_output") as view:
        page = view.page
        outer_height, inner_height = await _height(page, _OUTER), await _height(page, _INNER)
        await _scroll_to_copy(page, "following-output", outer_height + inner_height + 16)
        await _expect_at(page, _OUTER, 0)
        await _expect_at(page, _INNER, outer_height)
        await _expect_released(page, _OUTPUT)
        await capture_scene(view, "disclosure_component_phone_nested_after_output")


@pytest.mark.parametrize(
    ("scene", "viewport_name"), [("session_shell_calls_open", "desktop"), ("session_shell_calls_open_phone", "phone")]
)
@pytest.mark.parametrize("state", ["collapsed-hover", "expanded-hover", "tool-hover", "expanded-focus"])
async def test_disclosure_control_reaches_card_edges(
    scene: str, viewport_name: str, state: str, visual: VisualHarness
) -> None:
    async with open_scene(visual, scene) as view:
        page = view.page
        if state != "collapsed-hover":
            await _open_tool_run(page)
        if state == "tool-hover":
            control = (
                page.locator(".agentplane-step-details")
                .filter(has=page.locator(".agentplane-step-title:text-is('Bash')"))
                .locator(".agentplane-disclosure-summary")
                .first
            )
        else:
            control = page.locator(".agentplane-disclosure-summary").filter(has_text="tool calls").first
        if state == "tool-hover":
            await _focus(page, control)
        else:
            # A sticky control can already be visible while its card's top is far above the
            # viewport. Show the card's real rounded corners for this coverage check and capture.
            await page.locator('[aria-label="Thread history"]').evaluate("el => { el.scrollTop = 0; }")
            await wait_for_stable(page)
            await _in_viewport(control)
        card = control.locator("xpath=ancestor::*[@data-open][1]")
        control_box = await control.bounding_box()
        card_box = await card.bounding_box()
        assert control_box is not None
        assert card_box is not None
        # Allow the card's one-pixel border. The top and both sides belong to the actual control,
        # including the area that used to be inert padding around its rectangular hover fill.
        assert abs(control_box["x"] - card_box["x"]) <= 1
        assert abs(control_box["y"] - card_box["y"]) <= 1
        assert abs(control_box["x"] + control_box["width"] - card_box["x"] - card_box["width"]) <= 1
        assert await control.evaluate("el => parseFloat(getComputedStyle(el).borderTopLeftRadius)") > 0
        assert await control.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                return [[r.x + 5, r.y + 2], [r.right - 5, r.y + 2]].every(([x, y]) =>
                    el.contains(document.elementFromPoint(x, y)));
            }"""
        )
        if state == "expanded-focus":
            await control.focus()
            await page.keyboard.press("Tab")
            await page.keyboard.press("Shift+Tab")
            await expect(control).to_be_focused()
            assert await control.evaluate("el => el.matches(':focus-visible')")
        else:
            await control.hover(position={"x": 5, "y": 2})
            assert await control.evaluate("el => el.matches(':hover')")
        await capture_scene(view, scene, output_name=f"disclosure-{state}-{viewport_name}")
