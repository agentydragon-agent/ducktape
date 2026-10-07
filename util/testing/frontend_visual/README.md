# Python visual tests

Visual tests are ordinary async pytest tests. They load a fixture, perform Playwright
interactions, assert the result, then call the shared screenshot API. There is no
JSON/jq instruction interpreter and no browser-side test driver.

## Responsibilities

- **Tests** own fixture selection, readiness, actions, assertions, scrolling, pointer
  placement and screenshot checkpoints. Use normal functions and pytest parameterization.
- **TS harnesses** mount production components and provide synthetic fixture data or fake
  services. A shared/generated fixture catalog may enumerate data; it must not contain
  selectors, clicks, waits, or capture instructions.
- **`VisualHarness` / `VisualPage`** (`util/testing/visual_capture.py`) own browser lifecycle,
  render-health checks, screenshot mechanics and review publication.
- **`py_visual_test`** owns Bazel runfiles, the Python entry point and the `visual` tag.

## Example

```python
import pytest
import pytest_bazel
from playwright.async_api import expect

from util.testing.visual_capture import VisualHarness

# gazelle:include_dep //util/testing:visual_fixtures
pytest_plugins = ("util.testing.visual_fixtures",)
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_details(visual: VisualHarness) -> None:
    async with visual.open("example") as view:
        await view.page.get_by_role("button", name="Details").click()
        panel = view.page.get_by_role("region", name="Details")
        await expect(panel).to_be_visible()
        await view.capture("details", target=panel)


if __name__ == "__main__":
    pytest_bazel.main()
```

Pass `test_module`, `test_srcs`, direct `test_deps`, bundled `harness`, `assets` and
`title` to `py_visual_test`. Exclude macro-owned test sources from Gazelle so it does
not create a second test target. Shared helper modules remain Gazelle-managed.

`visual.open()` accepts browser geometry (`util/testing/viewports.py`), color scheme,
query parameters and an optional frozen instant. Inline harnesses use `window_globals`
instead of a query. The macro's `page_url` gives an inline document an origin for
storage; `served_documents` supplies mock iframe documents.

`view.capture()` takes a unique output name and optional caption. Pass a strict
`Locator` to crop one component, omit it to capture the viewport, or use
`full_page=True`. Crops retain the nearest-pixel rounding convention.
`devtools_viewport` retains device-pixel compatibility for existing galleries.
Duplicate output names within an execution fail instead of overwriting an image.

## Health and determinism

Each harness opening gets a fresh deterministic browser: pinned Chromium, font profile,
locale, timezone and frozen clock. Harness styles must pin animations before components
mount; inline pages include that CSS automatically. Capture waits for fonts, image decoding,
paint and the fixture network ledger, and checks uncaught page errors and escaped requests.
These are **not** application-readiness conditions: the test must assert its content first.
Capture does not click, scroll, or move the pointer.

Real-server tests may construct `VisualPage` before navigating an existing deterministic
page, with their own server setup and network policy. Diagnostic screenshots need not be
published as visual-review assets.

Screenshots and `visual-review.json` go to Bazel undeclared outputs. There are no
checked-in pixel baselines: behavior/render health are hard gates, while pixel changes
are reviewed through `devinfra/pr_visuals`. Preserve target names and asset filenames
when migrating so the publisher can match existing baselines.

Run browser tests on RBE through `bbr`, or use PR CI. Pytest selection/sharding and the
weekly `visual`-tagged determinism sweep continue to apply. Inspect both test results and
the PR visual comparison; a passing test is not proof of an unchanged image.
