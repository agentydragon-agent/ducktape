from __future__ import annotations

import pytest

from adgn.mcp.testing.simple_servers import SendMessageInput
from adgn.mcp.ui.server import EndTurnInput
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import MakeCall

pytestmark = pytest.mark.usefixtures()

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

"""E2E UI tests. Shared fixtures are provided in tests/agent/e2e/conftest.py."""


def test_ui_create_chat_and_restore(e2e_page, run_server, responses_factory, make_step_runner):
    """Create agent via UI, send two prompts, restart server, and verify hydration in snapshot.

    - FE: exercise Svelte UI flows (agent creation, chatting, rendering messages)
    - BE: exercise FastAPI HTTP+WS, agent container, persistence + restore
    - LLM: patched to deterministic tool-calls that emit ui messages
    """

    # Program two turns: **r1**, end; then **r2**, end
    runner = make_step_runner(
        steps=[
            MakeCall("ui", "send_message", SendMessageInput(mime="text/markdown", content="**r1**")),
            MakeCall("ui", "end_turn", EndTurnInput()),
            MakeCall("ui", "send_message", SendMessageInput(mime="text/markdown", content="**r2**")),
            MakeCall("ui", "end_turn", EndTurnInput()),
        ]
    )

    # Start server instance A
    s1 = run_server(lambda model: make_mock(runner.handle_request_async))

    # 1) Open UI and create agent via the UI
    e2e_page.goto(s1.base_url)
    e2e_page.create_agent_via_ui()

    # Extract agent_id from URL after agent is created
    e2e_page.page.wait_for_url("**/?(agent_id=*", timeout=10000)
    agent_id = e2e_page.extract_agent_id_from_url()

    # 2) Send first prompt and expect Assistant message r1
    e2e_page.send_prompt("hi")
    e2e_page.wait_for_message("r1")

    # 3) Send second prompt and expect Assistant message r2
    e2e_page.send_prompt("again")
    e2e_page.wait_for_message("r2")

    # Stop server A
    s1.stop()

    # Start server instance B (same DB)
    s2 = run_server(lambda model: make_mock(runner.handle_request_async))

    # 4) Re-open UI on the same agent id, wait for WS connected (dot), verify hydration
    e2e_page.goto_agent(s2.base_url, agent_id)
    e2e_page.wait_for_message("r1")
    e2e_page.wait_for_message("r2")

    # Cleanup
    s2.stop()
