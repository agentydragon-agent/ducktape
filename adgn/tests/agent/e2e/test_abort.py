from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.agent.helpers import api_create_agent, send_prompt
from tests.llm.support.openai_mock import make_mock

pytestmark = pytest.mark.usefixtures()

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


"""E2E Abort test. Shared fixtures are provided in tests/agent/e2e/conftest.py."""


def test_ui_abort_sampling(page: Page, run_server, responses_factory):
    """Start a long sampling call, click Abort in UI, and verify the run stops.

    - FE: exercise Abort button visibility/interaction
    - BE: exercise WS abort → session.cancel_active_run → sampling cancellation
    """

    state = {"i": 0}

    async def responses_create(_req):
        # Simulate a long-running first sampling call that should be cancelled by Abort
        state["i"] += 1
        if state["i"] == 1:
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                # Propagate cancellation so the agent treats this as aborted
                raise
            # If not cancelled (unexpected), return a message
            return responses_factory.make_assistant_message("too-late")
        return responses_factory.make_assistant_message("done")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent via API and open UI directly
    agent_id = api_create_agent(base)
    # Hook console logging for debugging WS issues
    page.on("console", lambda msg: print(f"[browser console] {msg.type}: {msg.text}"))
    page.goto(base + f"/?agent_id={agent_id}")

    # Wait for WS connected
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send a prompt to kick off sampling; Abort button should appear while running
    send_prompt(page, "start long task")

    # Wait for Abort button to become visible and click it
    abort_btn = page.get_by_role("button", name="Abort")
    abort_btn.wait_for(timeout=5000)
    abort_btn.click()

    # After abort, the UI should unblock; type a new draft and expect Send to enable
    page.wait_for_timeout(200)  # brief yield to allow UI update
    page.locator('textarea[placeholder^="Type a prompt"]').fill("draft after abort")
    page.locator('button:has-text("Send"):not([disabled])').wait_for(timeout=5000)

    # Ensure the long-running message was not rendered
    expect_none = page.locator(".messages .msg .text", has_text="too-late")
    assert expect_none.count() == 0

    s["stop"]()
