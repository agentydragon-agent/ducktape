"""OAuth consent layout at both widths and color schemes."""

from typing import Literal

import pytest
import pytest_bazel

from util.testing.viewports import Viewport
from util.testing.visual_capture import VisualHarness

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
@pytest.mark.parametrize("viewport", [Viewport(), Viewport(width=375, height=812)], ids=["desktop", "mobile"])
async def test_oauth_consent(visual: VisualHarness, viewport: Viewport, color_scheme: Literal["light", "dark"]) -> None:
    name = "OAuthPage" + ("_mobile" if viewport.width == 375 else "") + ("_dark" if color_scheme == "dark" else "")
    async with visual.open("OAuthPage", viewport=viewport, color_scheme=color_scheme) as view:
        await view.page.wait_for_selector('form[action^="/oauth/authorize/"] button', state="attached")
        await view.page.wait_for_selector("footer", state="attached")
        await view.capture(name, target=view.page.locator("#app"))


if __name__ == "__main__":
    pytest_bazel.main()
