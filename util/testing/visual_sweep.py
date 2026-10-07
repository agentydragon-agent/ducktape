"""Capture harness scenes with Playwright: one `test_scenario` per table row.

Run by the `py_visual_test` macro (`frontend_visual/py_visual_test.bzl`), either as its default main
module or as a collected test in a package-owned main module. The macro sets the environment
`SweepConfig` reads. The scenarios are the rows of a
`scenarios.json` (`visual_scenarios`); each is rendered, gated, and published as
`<outputName>-actual.png` (the suffix is the lane's choice) plus an entry in `visual-review.json`, for PR visual review
(`devinfra/pr_visuals`). There are no checked-in baselines: a scenario passes when it renders healthily.

The harness page is a `file://` `index.html` beside its bundle, told its scene by `?page=<name>`; or
(`InlinePage`) a document assembled in memory from the bundle and stylesheets and loaded with
`set_content`, told its scene by the scenario's `windowGlobals`. The in-memory page has no origin (no
`localStorage`, no origin to fetch from) unless the lane gives it a `page_url`, at which the page is served.
The request fence allows nothing at all; the one thing it answers is a document the lane serves under a
URL prefix (`served_documents`, for a shell that frames another origin).

A simple scenario can use selector-based `clicks` and `scrollToBottom`. A package-owned Python
test can name and drive an interaction-heavy scene, then call `capture_scenario` with its Playwright
driver. Both paths share the screenshot and visual-review publication machinery.

Selection is pytest's, which is what Bazel drives: `--test_filter=<scenario>` is `-k` (a scenario's
name is its test id), and `shard_count` is `util.testing.sharding`, filter first, then shard.
A scenario that fails fails its own test and the sweep goes on, so one run enumerates every broken scene.

Each scenario gets a fresh browser (about 0.1s on the RBE worker, against ~10s of rendering per shard),
not a page of one shared per shard. Viewport, device scale factor, touch and colour scheme are then
context options as Playwright intends, and what one scenario renders cannot depend on which others ran
before it or on which shard it landed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
import pytest_asyncio
import pytest_bazel
from more_itertools import one
from playwright.async_api import Page, Playwright, async_playwright
from pydantic import TypeAdapter

from util.bazel.runfiles import get_required_path
from util.testing.page_capture import WAIT_TIMEOUT_MS, PageErrors, assert_network_settled, wait_for_stable
from util.testing.undeclared_outputs import undeclared_outputs_dir
from util.testing.visual_capture import HarnessConfig, InlinePage, VisualHarness
from util.testing.visual_scenarios import Scenario, load_scenarios

_PATHS_BY_URL = TypeAdapter(dict[str, str])

# One event loop for the whole sweep, so one Playwright driver serves every scenario.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@dataclass(frozen=True)
class SweepConfig:
    harness_path: Path
    scenarios_path: Path
    title: str
    expected_font_family: str | None
    output_suffix: str
    # None: the harness is the `file://` page beside its bundle.
    inline_page: InlinePage | None = None
    devtools_viewport: bool = False
    # URL prefix -> the HTML file the request fence answers it with; see `RequestFence`.
    served_documents: Mapping[str, Path] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SweepConfig:
        """What `py_visual_test` sets: runfiles paths (`rlocationpath`) of the bundle and the table, and the rest as is."""
        return cls(
            harness_path=get_required_path(os.environ["HARNESS_PATH"]),
            scenarios_path=get_required_path(os.environ["SCENARIOS_PATH"]),
            title=os.environ["VISUAL_TITLE"],
            expected_font_family=os.environ.get("EXPECTED_FONT_FAMILY"),
            output_suffix=os.environ.get("OUTPUT_SUFFIX", "-actual"),
            inline_page=InlinePage.from_env() if os.environ.get("INLINE_PAGE") else None,
            devtools_viewport=bool(os.environ.get("DEVTOOLS_VIEWPORT")),
            served_documents={
                url: get_required_path(path)
                for url, path in _PATHS_BY_URL.validate_json(os.environ.get("SERVED_DOCUMENTS", "{}")).items()
            },
        )

    @property
    def harness_url(self) -> str:
        """The harness page: `index.html` beside the bundle, or beside the `dist/` directory holding it."""
        directory = self.harness_path.parent
        index = (directory.parent if directory.name == "dist" else directory) / "index.html"
        if not index.exists():
            raise FileNotFoundError(f"harness index.html not found for {self.harness_path}")
        # absolute(), not resolve(): the page pulls its bundle by relative path, which only exists beside
        # the runfiles symlink, not beside whatever it points to.
        return index.absolute().as_uri()

    @property
    def bundle_script(self) -> str:
        """The bundle's JavaScript: the file itself, or the one `.js` an esbuild directory output holds."""
        return (one(self.harness_path.glob("*.js")) if self.harness_path.is_dir() else self.harness_path).read_text(
            encoding="utf-8"
        )


def _check_scene_selection(scenario_name: str, scenario: Scenario, *, config: SweepConfig) -> None:
    """A scenario names its scene the way its harness page is told: by query for a file, by globals for an inline page."""
    if config.inline_page is None and scenario.window_globals is not None:
        raise ValueError(f"{scenario_name}: windowGlobals reach only an inline page, and this harness is a file")
    if config.inline_page is not None and scenario.query is not None:
        raise ValueError(f"{scenario_name}: an inline page has no URL for a query; name the scene by windowGlobals")


async def _wait_for_selectors(
    page: Page,
    page_errors: PageErrors,
    selectors: Iterable[str],
    *,
    state: Literal["attached", "visible", "hidden"],
    context: str,
    timeout_ms: int,
) -> None:
    for selector in selectors:
        await page_errors.wait_for(page.wait_for_selector(selector, state=state, timeout=timeout_ms), context=context)


async def capture_scenario(
    playwright: Playwright,
    scenario_name: str,
    scenario: Scenario,
    *,
    config: SweepConfig,
    output_dir: Path,
    drive: Callable[[Page], Awaitable[None]] | None = None,
    timeout_ms: int = WAIT_TIMEOUT_MS,
) -> None:
    """Render one scenario on its own browser; raise, naming it, if it is not healthy."""
    output_name = scenario.output_name or scenario_name
    _check_scene_selection(scenario_name, scenario, config=config)
    harness = VisualHarness(
        playwright,
        HarnessConfig(
            harness_path=config.harness_path,
            title=config.title,
            expected_font_family=config.expected_font_family,
            output_suffix=config.output_suffix,
            inline_page=config.inline_page,
            devtools_viewport=config.devtools_viewport,
            served_documents=config.served_documents,
        ),
        output_dir,
    )
    async with harness.open(
        scenario_name,
        viewport=scenario.viewport,
        color_scheme=scenario.color_scheme,
        query=scenario.query,
        window_globals=scenario.window_globals,
    ) as view:
        page = view.page
        page_errors = view.errors
        await _wait_for_selectors(
            page,
            page_errors,
            ("#app > *", *scenario.ready_selectors),
            state="attached",
            context=output_name,
            timeout_ms=timeout_ms,
        )
        for frame_selector, selector in scenario.ready_frames.items():
            await page_errors.wait_for(
                page.frame_locator(frame_selector).locator(selector).wait_for(state="attached", timeout=timeout_ms),
                context=output_name,
            )
        # Last, so fonts, images and paint settle around whatever the scene's own conditions let in.
        await wait_for_stable(page)
        if drive is not None:
            await assert_network_settled(page, context=output_name, timeout_ms=timeout_ms)
            await drive(page)
            await wait_for_stable(page)
        if scenario.clicks or scenario.scroll_to_bottom is not None:
            # An interaction acts on a page whose first fetches have landed: its target may be replaced under it.
            await assert_network_settled(page, context=output_name, timeout_ms=timeout_ms)
        for click in scenario.clicks:
            await page.locator(click.selector).click(timeout=timeout_ms)
            await _wait_for_selectors(
                page, page_errors, click.expect_visible, state="visible", context=output_name, timeout_ms=timeout_ms
            )
            await _wait_for_selectors(
                page, page_errors, click.expect_hidden, state="hidden", context=output_name, timeout_ms=timeout_ms
            )
            await wait_for_stable(page)
            await assert_network_settled(page, context=output_name, timeout_ms=timeout_ms)
            # A click leaves the pointer on its target, and a tooltip it opened would stay open into the capture.
            await page.mouse.move(0, 0)
            await wait_for_stable(page)
        # A pointer state no page script can make: :hover and a real touch. Settled again for what it shows.
        if scenario.hover:
            await page.hover(scenario.hover, timeout=timeout_ms)
        if scenario.tap:
            await page.tap(scenario.tap, timeout=timeout_ms)
        if scenario.hover or scenario.tap:
            await wait_for_stable(page)
        await _wait_for_selectors(
            page, page_errors, scenario.hidden_selectors, state="hidden", context=output_name, timeout_ms=timeout_ms
        )
        if scenario.scroll_to_bottom is not None:
            await page.eval_on_selector(
                scenario.scroll_to_bottom, "element => { element.scrollTop = element.scrollHeight; }"
            )
            await wait_for_stable(page)
        await assert_network_settled(page, context=output_name, timeout_ms=timeout_ms)
        await view.capture(
            output_name,
            label=scenario.label,
            target=None if scenario.capture_viewport else page.locator(scenario.element),
        )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "scenario_name" not in metafunc.fixturenames:
        return
    if not (scenarios := load_scenarios(SweepConfig.from_env().scenarios_path)):
        # An empty parameter set is skipped, which Bazel reports as a pass.
        raise ValueError("the scenario table is empty")
    metafunc.parametrize(("scenario_name", "scenario"), scenarios.items(), ids=list(scenarios))


@pytest.fixture(scope="session")
def sweep_config() -> SweepConfig:
    return SweepConfig.from_env()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def playwright_driver() -> AsyncIterator[Playwright]:
    async with async_playwright() as playwright:
        yield playwright


async def test_scenario(
    scenario_name: str, scenario: Scenario, playwright_driver: Playwright, sweep_config: SweepConfig
) -> None:
    await capture_scenario(
        playwright_driver, scenario_name, scenario, config=sweep_config, output_dir=undeclared_outputs_dir()
    )


def main() -> None:
    # This file is the test module as well as the entry point, so pytest is pointed at it by path:
    # its name is not one pytest collects on its own.
    pytest_bazel.main([*sys.argv[1:], __file__])


if __name__ == "__main__":
    main()
