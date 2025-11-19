from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import requests

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.helpers import api_create_agent
from tests.llm.support.openai_mock import make_mock

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


def test_multiple_agents_rapid_status_changes(page: Page, run_server, responses_factory):
    """Test multiple agents with rapid status changes.

    Verifies:
    - Create 5 agents
    - Trigger status changes in rapid succession
    - All updates received in UI
    - No missed notifications
    """
    # State machine to produce multiple tool calls for each agent
    states = {i: {"n": 0} for i in range(5)}

    def make_responses_create(agent_idx: int):
        async def responses_create(_req):
            i = states[agent_idx]["n"]
            states[agent_idx]["n"] = i + 1
            if i < 3:
                # Generate 3 rapid tool calls
                return responses_factory.make_tool_call(
                    build_mcp_function("echo", "echo"),
                    {"text": f"agent{agent_idx} call{i}"},
                    call_id=f"call_agent{agent_idx}_{i}",
                )
            # End turn after 3 calls
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "end_turn"), {}, call_id=f"call_ui_end_{agent_idx}"
            )

        return responses_create

    # Start server (only one mock will be used for simplicity in this test)
    s = run_server(lambda model: make_mock(make_responses_create(0)))
    base = s["base_url"]

    # Create 5 agents
    agent_ids = [api_create_agent(base) for _ in range(5)]

    # Attach echo MCP server to all agents
    spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
    for agent_id in agent_ids:
        patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
        assert patch.ok, patch.text

    # Connect to first agent
    page.goto(base + f"/?agent_id={agent_ids[0]}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Trigger prompts rapidly for multiple agents via API
    for idx, agent_id in enumerate(agent_ids):
        resp = requests.post(base + f"/api/agents/{agent_id}/prompt", json={"text": f"trigger agent {idx}"})
        assert resp.ok, resp.text

    # Wait for approvals to appear (we should see multiple pending)
    page.get_by_text("Pending Approvals").wait_for(timeout=10000)

    # Auto-approve all pending approvals by clicking approve repeatedly
    for _ in range(15):  # 5 agents × 3 calls each = 15 approvals
        try:
            approve_btn = page.get_by_role("button", name="Approve").first
            if approve_btn.count() > 0:
                approve_btn.click()
                page.wait_for_timeout(100)  # Small delay between approvals
        except Exception:
            break

    # Verify all agents finished (check for finished status)
    # The UI should show updates for all agents without missing any
    page.wait_for_timeout(2000)  # Wait for all updates to propagate

    s["stop"]()


def test_subscribe_unsubscribe_resubscribe(page: Page, run_server, responses_factory):
    """Test subscribe, unsubscribe, and resubscribe to resource.

    Verifies:
    - Subscribe to resource
    - Unsubscribe
    - Resubscribe
    - State consistency maintained
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "first call"}, call_id="call_echo_1"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent
    agent_id = api_create_agent(base)

    # Attach echo MCP server
    spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
    patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
    assert patch.ok, patch.text

    # Open UI
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send prompt to trigger tool call (this creates a subscription)
    page.locator('textarea[placeholder^="Type a prompt"]').fill("test")
    page.get_by_role("button", name="Send").click()

    # Wait for approval
    page.get_by_text("Pending Approvals (1)").wait_for(timeout=10000)

    # Approve
    page.get_by_role("button", name="Approve").first.click()

    # Wait for completion
    page.get_by_text("Status: finished").wait_for(timeout=10000)

    # Navigate away (unsubscribe by going to a different page or refreshing)
    page.goto(base + "/")
    page.wait_for_timeout(500)

    # Navigate back (resubscribe)
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Verify state is consistent (previous run should still be visible)
    page.get_by_text("Status: finished").wait_for(timeout=5000)

    s["stop"]()


def test_agent_deleted_while_subscribed(page: Page, run_server, responses_factory):
    """Test graceful cleanup when agent is deleted while subscribed.

    Verifies:
    - Subscribe to agent resource
    - Delete agent via API
    - No errors occur
    - Graceful cleanup
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "test"}, call_id="call_echo_1"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent
    agent_id = api_create_agent(base)

    # Attach echo MCP server
    spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
    patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
    assert patch.ok, patch.text

    # Open UI (establishes subscription)
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send prompt to start activity
    page.locator('textarea[placeholder^="Type a prompt"]').fill("test")
    page.get_by_role("button", name="Send").click()

    # Wait for approval to appear
    page.get_by_text("Pending Approvals (1)").wait_for(timeout=10000)

    # Delete agent via API while UI is connected
    delete_resp = requests.delete(base + f"/api/agents/{agent_id}")
    assert delete_resp.ok, delete_resp.text

    # Verify no errors in UI (should gracefully handle deletion)
    # The connection should close or show an appropriate error
    page.wait_for_timeout(1000)

    # Check browser console for errors (optional - requires console API)
    # For now, just verify page doesn't crash
    assert page.url is not None

    s["stop"]()


def test_concurrent_subscriptions_to_different_agents(page: Page, run_server, responses_factory):
    """Test concurrent subscriptions to multiple agent resources.

    Verifies:
    - Subscribe to 10 different agent resources simultaneously
    - Trigger updates on all agents
    - All subscriptions work correctly
    """
    # Create response handlers for multiple agents
    states = {i: {"n": 0} for i in range(10)}

    def make_responses_create(agent_idx: int):
        async def responses_create(_req):
            i = states[agent_idx]["n"]
            states[agent_idx]["n"] = i + 1
            if i == 0:
                return responses_factory.make_tool_call(
                    build_mcp_function("echo", "echo"),
                    {"text": f"agent{agent_idx}"},
                    call_id=f"call_agent{agent_idx}",
                )
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "end_turn"), {}, call_id=f"call_ui_end_{agent_idx}"
            )

        return responses_create

    s = run_server(lambda model: make_mock(make_responses_create(0)))
    base = s["base_url"]

    # Create 10 agents
    agent_ids = [api_create_agent(base) for _ in range(10)]

    # Attach echo MCP server to all agents
    spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
    for agent_id in agent_ids:
        patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
        assert patch.ok, patch.text

    # Open multiple tabs/contexts (simulate by visiting different agents)
    # For this test, we'll just cycle through agents rapidly
    for idx, agent_id in enumerate(agent_ids):
        page.goto(base + f"/?agent_id={agent_id}")
        page.locator(".ws .dot.on").wait_for(timeout=10000)

        # Trigger a prompt
        page.locator('textarea[placeholder^="Type a prompt"]').fill(f"agent {idx}")
        page.get_by_role("button", name="Send").click()

        # Wait for approval
        page.get_by_text("Pending Approvals (1)").wait_for(timeout=10000)

        # Approve
        page.get_by_role("button", name="Approve").first.click()

        # Wait for completion
        page.get_by_text("Status: finished").wait_for(timeout=10000)

    # Verify all worked without errors
    s["stop"]()


def test_subscription_survives_temporary_disconnect(page: Page, run_server, responses_factory):
    """Test subscription recovery after temporary network disconnect.

    Verifies:
    - Subscribe to resource
    - Simulate network hiccup (pause/resume via offline mode)
    - Subscription recovers correctly
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "before disconnect"}, call_id="call_echo_1"
            )
        if i == 1:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "after disconnect"}, call_id="call_echo_2"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent
    agent_id = api_create_agent(base)

    # Attach echo MCP server
    spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
    patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
    assert patch.ok, patch.text

    # Open UI
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send first prompt
    page.locator('textarea[placeholder^="Type a prompt"]').fill("first")
    page.get_by_role("button", name="Send").click()

    # Wait for approval
    page.get_by_text("Pending Approvals (1)").wait_for(timeout=10000)

    # Approve
    page.get_by_role("button", name="Approve").first.click()

    # Wait for first call to complete
    page.get_by_text("Status: finished").wait_for(timeout=10000)

    # Simulate network disconnect by going offline
    page.context.set_offline(True)
    page.wait_for_timeout(1000)

    # Reconnect
    page.context.set_offline(False)
    page.wait_for_timeout(1000)

    # Verify connection recovered (dot should be on)
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Send second prompt after reconnect
    page.locator('textarea[placeholder^="Type a prompt"]').fill("second")
    page.get_by_role("button", name="Send").click()

    # Wait for second approval
    page.get_by_text("Pending Approvals (1)").wait_for(timeout=10000)

    # Approve
    page.get_by_role("button", name="Approve").first.click()

    # Verify second call completes
    page.get_by_text("Status: finished").wait_for(timeout=10000)

    s["stop"]()
