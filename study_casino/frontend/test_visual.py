"""Render fixture states with explicit Python readiness and capture."""

import pytest
import pytest_bazel
from playwright.async_api import expect

from util.testing.viewports import Viewport
from util.testing.visual_capture import VisualHarness

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize("scene", ["main_page", "streak_rest", "active_bonus_countdown", "active_bonus_unlocked"])
async def test_main_page(visual: VisualHarness, scene: str) -> None:
    async with visual.open(scene, viewport=Viewport(height=1400, width=1200)) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.page.wait_for_selector('[data-testid="sync-banner-offline"]', state="attached")
        await view.capture(scene, target=view.page.locator("#app"))


@pytest.mark.parametrize("scene", ["changelog"])
async def test_changelog(visual: VisualHarness, scene: str) -> None:
    async with visual.open(scene, viewport=Viewport(height=900, width=1200)) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.capture(scene, target=view.page.locator("#app"))


@pytest.mark.parametrize("scene", ["session_award"])
async def test_session_award(visual: VisualHarness, scene: str) -> None:
    async with visual.open(scene, viewport=Viewport()) as view:
        await expect(view.page.locator("#app > *").first).to_be_attached()
        await view.capture(scene, target=view.page.locator("#shot"))


if __name__ == "__main__":
    pytest_bazel.main()
