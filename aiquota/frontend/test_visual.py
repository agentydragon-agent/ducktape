"""Dashboard fixtures across themes, plus the two narrow layout cases."""

import json
import os
from typing import Literal

import pytest
import pytest_bazel
from playwright.async_api import expect

from util.bazel.runfiles import get_required_path
from util.testing.visual_capture import VisualHarness
from util.testing.viewports import Viewport

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")

_SCENES = tuple(json.loads(get_required_path(os.environ["FIXTURE_CATALOG"]).read_bytes()))
if not _SCENES:
    raise ValueError("the dashboard fixture catalog is empty")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
@pytest.mark.parametrize("scene", _SCENES)
async def test_dashboard(visual: VisualHarness, scene: str, color_scheme: Literal["light", "dark"]) -> None:
    async with visual.open(
        scene, query={"scene": scene}, viewport=Viewport(width=1200, height=900, device_scale_factor=2), color_scheme=color_scheme
    ) as view:
        await expect(view.page.locator(".aiquota-card").first).to_be_attached()
        await view.capture(f"{scene}-{color_scheme}", label=f"{scene} · {color_scheme}", target=view.page.locator("#app"))


@pytest.mark.parametrize("scene", ["hot", "paid_credits"])
async def test_narrow_dashboard(visual: VisualHarness, scene: str) -> None:
    async with visual.open(
        scene, query={"scene": scene}, viewport=Viewport(width=420, height=900, device_scale_factor=2), color_scheme="dark"
    ) as view:
        await expect(view.page.locator(".aiquota-card").first).to_be_attached()
        await view.capture(f"{scene}-narrow", label=f"{scene.replace('_', ' ')} · dark · narrow", target=view.page.locator("#app"))


if __name__ == "__main__":
    pytest_bazel.main()
