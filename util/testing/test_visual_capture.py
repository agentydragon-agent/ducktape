"""The capture API preserves health gates without owning the test's interactions."""

import json
from pathlib import Path

import pytest
import pytest_bazel
from playwright.async_api import Playwright, expect

from util.testing.visual_capture import HarnessConfig, VisualHarness
from util.testing.visual_scenarios import Viewport

# gazelle:include_dep //util:playwright
pytest_plugins = ("util.playwright",)


@pytest.fixture
def harness(playwright: Playwright, tmp_path: Path) -> VisualHarness:
    bundle = tmp_path / "harness.js"
    bundle.write_text("document.querySelector('button').onclick = () => document.querySelector('#shot').textContent = 'Opened';")
    (tmp_path / "index.html").write_text(
        "<!doctype html><style>body { margin: 0 } #shot { width: 100px; height: 40px }</style>"
        "<div id='app'><button>Open</button><div id='shot'>Closed</div></div><script src='./harness.js'></script>"
    )
    return VisualHarness(
        playwright,
        HarnessConfig(harness_path=bundle, title="API test", expected_font_family=None, output_suffix="-actual"),
        tmp_path / "out",
    )


async def test_test_owns_interaction_and_capture(harness: VisualHarness) -> None:
    async with harness.open("plain") as view:
        await expect(view.page.locator("#shot")).to_have_text("Closed")
        await view.page.get_by_role("button", name="Open").click()
        await expect(view.page.locator("#shot")).to_have_text("Opened")
        path = await view.capture("opened", target=view.page.locator("#shot"), label="Opened panel")
    assert path.name == "opened-actual.png"
    manifest = json.loads((harness.output_dir / "visual-review.json").read_text())
    assert manifest["assets"] == [{"path": "opened-actual.png", "label": "Opened panel"}]


async def test_multiple_checkpoints_have_distinct_outputs(harness: VisualHarness) -> None:
    async with harness.open("plain") as view:
        first = await view.capture("closed", target=view.page.locator("#shot"))
        await view.page.get_by_role("button", name="Open").click()
        second = await view.capture("opened", target=view.page.locator("#shot"))
        assert first.read_bytes() != second.read_bytes()
        with pytest.raises(FileExistsError):
            await view.capture("closed")
        assert first.read_bytes() != second.read_bytes()


async def test_ambiguous_crop_fails_before_publication(harness: VisualHarness) -> None:
    async with harness.open("plain") as view:
        with pytest.raises(ValueError, match="exactly one"):
            await view.capture("ambiguous", target=view.page.locator("div"))
    assert not harness.output_dir.exists()


async def test_no_capture_can_hide_a_page_error(harness: VisualHarness) -> None:
    with pytest.raises(AssertionError, match="deliberate crash"):
        async with harness.open("plain") as view:
            await view.page.evaluate("() => window.dispatchEvent(new ErrorEvent('error', {message: 'deliberate crash', error: new Error('deliberate crash')}))")


async def test_external_request_fails_before_publication(harness: VisualHarness) -> None:
    with pytest.raises(AssertionError, match="requests escaped"):
        async with harness.open("plain") as view:
            await view.page.evaluate("() => fetch('https://escaped.test/').catch(() => {})")
            await view.capture("escaped")
    assert not harness.output_dir.exists()


async def test_new_page_is_isolated_and_pixels_repeat(harness: VisualHarness) -> None:
    async with harness.open("plain", viewport=Viewport(width=300, height=200)) as view:
        first = await view.capture("first", target=view.page.locator("#shot"))
        await view.page.get_by_role("button", name="Open").click()
    async with harness.open("plain", viewport=Viewport(width=300, height=200)) as view:
        await expect(view.page.locator("#shot")).to_have_text("Closed")
        second = await view.capture("second", target=view.page.locator("#shot"))
    assert first.read_bytes() == second.read_bytes()


if __name__ == "__main__":
    pytest_bazel.main()
