from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import pytest

from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.helpers import api_create_agent, send_prompt
from tests.llm.support.openai_mock import make_mock

pytestmark = pytest.mark.usefixtures()

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


"""E2E UI tests. Shared fixtures are provided in tests/agent/e2e/conftest.py."""


def _extract_agent_id(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    vals = qs.get("agent_id")
    return vals[0] if vals else None


def test_ui_create_chat_and_restore(page: Page, run_server, responses_factory):
    """Create agent via UI, send two prompts, restart server, and verify hydration in snapshot.

    - FE: exercise Svelte UI flows (agent creation, chatting, rendering messages)
    - BE: exercise FastAPI HTTP+WS, agent container, persistence + restore
    - LLM: patched to deterministic tool-calls that emit ui messages
    """

    # Program two turns: **r1**, end; then **r2**, end
    state = {"i": 0}

    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "send_message"),
                {"mime": "text/markdown", "content": "**r1**"},
                call_id="call_ui_msg_r1",
            )
        if i == 1:
            return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_r1")
        if i == 2:
            return responses_factory.make_tool_call(
                build_mcp_function("ui", "send_message"),
                {"mime": "text/markdown", "content": "**r2**"},
                call_id="call_ui_msg_r2",
            )
        return responses_factory.make_tool_call(build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end_r2")

    # Inject deterministic OpenAI model via DI
    # Start server instance A
    s1 = run_server(lambda model: make_mock(responses_create))
    base1 = s1["base_url"]

    # 1) Create agent via backend API, then open UI directly on that agent
    agent_id = api_create_agent(base1)
    # Hook console logging for debugging WS issues
    page.on("console", lambda msg: print(f"[browser console] {msg.type}: {msg.text}"))
    page.goto(base1 + f"/?agent_id={agent_id}")
    # Wait for either WS connected or an error banner, print error if seen
    try:
        # Prefer stable selector over text to avoid timing blips
        page.locator(".ws .dot.on").wait_for(timeout=10000)
    except Exception:
        # Surface any UI error banner for diagnosis
        try:
            err_text = page.locator(".error").first.text_content(timeout=1000) or ""
            print("UI error banner:", err_text)
        except Exception:
            pass
        raise

    # 2) Send first prompt and expect Assistant message r1
    send_prompt(page, "hi")
    page.locator(".messages .msg .text", has_text="r1").wait_for(timeout=5000)

    # 3) Send second prompt and expect Assistant message r2
    send_prompt(page, "again")
    page.locator(".messages .msg .text", has_text="r2").wait_for(timeout=5000)

    # Stop server A
    s1["stop"]()

    # Start server instance B (same DB)
    s2 = run_server(lambda model: make_mock(responses_create))
    base2 = s2["base_url"]

    # 4) Re-open UI on the same agent id, wait for WS connected (dot), verify hydration
    page.goto(base2 + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)
    page.locator(".messages .msg .text", has_text="r1").wait_for(timeout=5000)
    page.locator(".messages .msg .text", has_text="r2").wait_for(timeout=5000)

    # Cleanup
    s2["stop"]()
