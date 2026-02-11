from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from adgn.mcp.testing.simple_servers import EchoInput
from adgn.mcp.ui.server import EndTurnInput
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import MakeCall

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


def test_approvals_delivery_and_user_approve(e2e_page, run_server, responses_factory, make_step_runner):
    """Agent attempts a tool call → policy asks → UI shows pending → user approves → tool runs.

    Flow:
      - Create agent via UI with default preset
      - Model first response is a tool call to echo; second response is ui.end_turn
      - UI shows pending approval immediately; clicking Approve triggers execution
      - Run finishes without a reload

    Note: This test may fail if the echo server is not available in the default preset.
    Ideally, we'd use MCP tools to attach the echo server, but that's not yet available via UI.
    """

    runner = make_step_runner(
        steps=[MakeCall("echo", "echo", EchoInput(text="hello")), MakeCall("ui", "end_turn", EndTurnInput())]
    )

    s = run_server(lambda model: make_mock(runner.handle_request_async))

    e2e_page.goto(s.base_url)
    e2e_page.create_agent_via_ui()

    # Send a prompt to trigger the tool call that requires approval
    e2e_page.send_prompt("use echo tool")

    # Pending approval should show up without reload; Approvals tab is the default
    e2e_page.wait_for_text("Pending Approvals (1)")

    # Click Approve on the first pending item
    e2e_page.click_approve()

    # Run should proceed to end_turn and finish; wait for UI to reflect completion
    e2e_page.wait_for_text("Status: finished")

    s.stop()
