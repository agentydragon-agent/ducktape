"""Pytest plugin for package-owned visual tests."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from playwright.async_api import Playwright, async_playwright, expect

from util.testing.page_capture import WAIT_TIMEOUT_MS
from util.testing.undeclared_outputs import undeclared_outputs_dir
from util.testing.visual_capture import HarnessConfig, VisualHarness


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def playwright_driver() -> AsyncIterator[Playwright]:
    expect.set_options(timeout=WAIT_TIMEOUT_MS)
    async with async_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="session")
def visual(playwright_driver: Playwright) -> VisualHarness:
    return VisualHarness(playwright_driver, HarnessConfig.from_env(), undeclared_outputs_dir())
