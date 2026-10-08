"""Dashboard fixtures across themes, plus the two narrow layout cases."""

import json
import os
from collections.abc import AsyncIterator
from typing import Literal

import pytest
import pytest_asyncio
import pytest_bazel
from playwright.async_api import expect

from util.bazel.runfiles import get_required_path
from util.testing.viewports import Viewport
from util.testing.visual_capture import VisualHarness, VisualPage

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")

_SCENES = tuple(json.loads(get_required_path(os.environ["FIXTURE_CATALOG"]).read_bytes()))
if not _SCENES:
    raise ValueError("the dashboard fixture catalog is empty")


@pytest_asyncio.fixture(loop_scope="session")
async def view(
    visual: VisualHarness, scene: str, color_scheme: Literal["light", "dark"], viewport: Viewport, capture_name: str
) -> AsyncIterator[VisualPage]:
    async with visual.open(
        query={"scene": scene}, viewport=viewport, color_scheme=color_scheme, capture_name=capture_name
    ) as view:
        yield view


@pytest.mark.parametrize(
    ("scene", "color_scheme", "viewport"),
    [
        pytest.param(scene, scheme, Viewport(width=1200, height=900, device_scale_factor=2), id=f"{scene}-{scheme}")
        for scene in _SCENES
        for scheme in ("light", "dark")
    ]
    + [
        pytest.param(scene, "dark", Viewport(width=420, height=900, device_scale_factor=2), id=f"{scene}-dark-narrow")
        for scene in ("hot", "paid_credits")
    ],
)
async def test_dashboard(view: VisualPage) -> None:
    await expect(view.page.locator(".aiquota-card").first).to_be_attached()
    await view.capture(target=view.page.locator("#app"))


if __name__ == "__main__":
    pytest_bazel.main()
