from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.helpers import api_create_agent, approve_first_pending, attach_echo_mcp, send_prompt, wait_for_pending_approvals
from tests.llm.support.openai_mock import make_mock

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


def test_approvals_delivery_and_user_approve(page: Page, run_server, responses_factory):
    """Agent attempts a tool call → policy asks → UI shows pending → user approves → tool runs.

    Flow:
      - Attach in-proc echo MCP server via HTTP (inproc factory spec)
      - Model first response is a tool call to echo; second response is ui.end_turn
      - UI shows pending approval immediately; clicking Approve triggers execution
      - Run finishes without a reload
    """

    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "hello"}, call_id="call_echo"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent via helper
    agent_id = api_create_agent(base)

    # Attach echo server
    attach_echo_mcp(base, agent_id)

    # Open UI and connect WS
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send a prompt to trigger the tool call that requires approval
    send_prompt(page, "use echo tool")

    # Pending approval should show up without reload; Approvals tab is the default
    wait_for_pending_approvals(page, count=1)
    # Click Approve on the first pending item
    approve_first_pending(page)

    # Run should proceed to end_turn and finish; wait for UI to reflect completion
    page.get_by_text("Status: finished").wait_for(timeout=10000)

    s["stop"]()
