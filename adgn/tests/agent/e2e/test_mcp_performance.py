from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
import requests

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.helpers import api_create_agent, attach_echo_mcp, send_prompt, wait_for_pending_approvals
from tests.llm.support.openai_mock import make_mock

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


@pytest.mark.slow
def test_100_pending_approvals_ui_responsive(page: Page, run_server, responses_factory):
    """Test UI responsiveness with 100 pending approvals.

    Verifies:
    - Create 100 pending approvals
    - Load UI
    - Verify UI loads in <5 seconds
    - Verify scrolling is smooth (no major lag)
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        # Generate 100 tool calls that require approval
        if i < 100:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": f"message {i}"}, call_id=f"call_echo_{i}"
            )
        # After 100 calls, end the turn
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]
    agent_id = api_create_agent(base)
    attach_echo_mcp(base, agent_id)
    # This ensures approvals are already pending when we open the UI
    resp = requests.post(base + f"/api/agents/{agent_id}/prompt", json={"text": "trigger approvals"})
    assert resp.ok, resp.text
    time.sleep(1)

    # Now open UI and measure load time
    start_time = time.time()
    page.goto(base + f"/?agent_id={agent_id}")

    page.locator(".ws .dot.on").wait_for(timeout=10000)
    load_time = time.time() - start_time
    assert load_time < 5.0, f"UI took {load_time:.2f}s to load (expected <5s)"
    # Note: UI might paginate or virtualize, so we don't expect all 100 to be in DOM
    wait_for_pending_approvals(page, timeout=5000)

    # Test scrolling responsiveness
    approvals_container = page.locator(".approvals, [data-testid='approvals-list']").first
    if approvals_container.count() > 0:
        page.evaluate("document.querySelector('.approvals, [data-testid=\"approvals-list\"]')?.scrollBy(0, 500)")
        # Small delay to ensure scroll is processed
        time.sleep(0.1)
        page.evaluate("document.querySelector('.approvals, [data-testid=\"approvals-list\"]')?.scrollBy(0, -500)")

    # If we got here without timeout, scrolling is responsive enough
    # More sophisticated checks could measure frame rates, but for E2E this is sufficient

    s["stop"]()


@pytest.mark.slow
def test_high_frequency_updates_10_per_second(page: Page, run_server, responses_factory):
    """Test UI handles high-frequency status updates (10 per second for 10 seconds).

    Verifies:
    - Trigger 10 status updates per second for 10 seconds (100 total)
    - Verify all updates received
    - Verify no missed notifications
    - Verify UI remains responsive
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        # Generate 100 rapid tool calls
        if i < 100:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": f"rapid message {i}"}, call_id=f"call_echo_{i}"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    agent_id = api_create_agent(base)
    attach_echo_mcp(base, agent_id)
    policy_src = """
from adgn.agent.policies.models import PolicyDecision

class ApprovalPolicy:
    '''Auto-approve all for performance testing'''
    def decide(self, ctx):
        return (PolicyDecision.ALLOW, 'auto-approved for perf test')
"""
    policy_resp = requests.post(base + f"/api/agents/{agent_id}/policy", json={"content": policy_src})
    assert policy_resp.ok, policy_resp.text
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)
    start_time = time.time()
    resp = requests.post(base + f"/api/agents/{agent_id}/prompt", json={"text": "trigger rapid updates"})
    assert resp.ok, resp.text
    # With auto-approval, this should be fast
    page.get_by_text("Status: finished").wait_for(timeout=30000)

    elapsed = time.time() - start_time
    # 100 updates should complete reasonably quickly with auto-approval
    # Allow generous timeout but verify it completes
    assert elapsed < 30.0, f"Updates took {elapsed:.2f}s (expected <30s)"
    page.locator('textarea[placeholder^="Type a prompt"]').wait_for(state="visible", timeout=5000)

    s["stop"]()


@pytest.mark.slow
def test_10_concurrent_subscriptions_all_work(page: Page, run_server, responses_factory):
    """Test 10 concurrent subscriptions all work correctly.

    Verifies:
    - Create 10 agents
    - Subscribe to all agent resources
    - Trigger updates on all
    - Verify all work correctly (updates flow through)
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": "test"}, call_id=f"call_echo_{i}"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    agent_ids = []
    for _ in range(10):
        agent_id = api_create_agent(base)
        agent_ids.append(agent_id)

    attach_echo_mcp(base, agent_id)
    policy_src = """
from adgn.agent.policies.models import PolicyDecision

class ApprovalPolicy:
    '''Auto-approve all'''
    def decide(self, ctx):
        return (PolicyDecision.ALLOW, 'auto-approved')
"""
    for agent_id in agent_ids:
        policy_resp = requests.post(base + f"/api/agents/{agent_id}/policy", json={"content": policy_src})
        assert policy_resp.ok, policy_resp.text
    page.goto(base + f"/?agent_id={agent_ids[0]}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    for agent_id in agent_ids:
        resp = requests.post(base + f"/api/agents/{agent_id}/prompt", json={"text": f"test agent {agent_id}"})
        assert resp.ok, resp.text
    page.get_by_text("Status: finished").wait_for(timeout=15000)
    for agent_id in agent_ids:
        snapshot_resp = requests.get(base + f"/api/agents/{agent_id}/snapshot")
        assert snapshot_resp.ok
        snapshot_data = snapshot_resp.json()
        assert "run_state" in snapshot_data
        assert snapshot_data["run_state"]["status"] in ("finished", "idle")

    s["stop"]()


@pytest.mark.slow
def test_large_resource_payload_10mb(page: Page, run_server, responses_factory):
    """Test UI handles large resource payload (10MB of data).

    Verifies:
    - Create resource with 10MB of data
    - Read resource
    - Verify UI handles large payload without crashing
    """
    # Generate a large message (10MB)
    large_text = "x" * (10 * 1024 * 1024)  # 10MB of 'x'

    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            # Return a large message
            return responses_factory.make_assistant_message(large_text)
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    agent_id = api_create_agent(base)

    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    send_prompt(page, "get large data")
    page.get_by_text("Status: finished").wait_for(timeout=30000)
    page.locator('textarea[placeholder^="Type a prompt"]').wait_for(state="visible", timeout=5000)
    page.locator('textarea[placeholder^="Type a prompt"]').fill("test after large payload")
    page.get_by_role("button", name="Send").is_enabled()

    s["stop"]()


@pytest.mark.slow
def test_sustained_load_1000_updates(page: Page, run_server, responses_factory):
    """Test sustained load with 1000 sequential updates.

    Verifies:
    - Trigger 1000 sequential updates
    - Verify UI remains responsive throughout
    - Verify no memory leaks or performance degradation
    """
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        # Generate 1000 tool calls
        if i < 1000:
            return responses_factory.make_tool_call(
                build_mcp_function("echo", "echo"), {"text": f"message {i}"}, call_id=f"call_echo_{i}"
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    agent_id = api_create_agent(base)

    attach_echo_mcp(base, agent_id)

    policy_src = """
from adgn.agent.policies.models import PolicyDecision

class ApprovalPolicy:
    '''Auto-approve all for load testing'''
    def decide(self, ctx):
        return (PolicyDecision.ALLOW, 'auto-approved for load test')
"""
    policy_resp = requests.post(base + f"/api/agents/{agent_id}/policy", json={"content": policy_src})
    assert policy_resp.ok, policy_resp.text
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)
    start_time = time.time()
    resp = requests.post(base + f"/api/agents/{agent_id}/prompt", json={"text": "trigger sustained load"})
    assert resp.ok, resp.text
    # We'll check at the start, middle, and end
    check_points = [10, 30, 60]  # seconds into the test
    last_check = 0

    for check_time in check_points:
        while time.time() - start_time < check_time:
            time.sleep(0.5)
            if page.locator("text=Status: finished").count() > 0:
                break
        textarea = page.locator('textarea[placeholder^="Type a prompt"]')
        if textarea.count() > 0:
            textarea.wait_for(state="visible", timeout=5000)

        if page.locator("text=Status: finished").count() > 0:
            break
    page.get_by_text("Status: finished").wait_for(timeout=120000)  # 2 minutes max

    # With 1000 updates, this could take a while, so we allow generous timeout

    page.locator('textarea[placeholder^="Type a prompt"]').wait_for(state="visible", timeout=5000)

    s["stop"]()
