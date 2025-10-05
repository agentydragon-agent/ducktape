from __future__ import annotations

from typing import Any, Callable

import pytest

from adgn.agent.server.app import create_app
from tests.agent.helpers import api_create_agent, start_uvicorn_app
from tests.llm.support.openai_mock import make_mock

# Skip if Playwright is not installed; bind Page from returned module
playwright = pytest.importorskip("playwright.sync_api")
Page = playwright.Page  # type: ignore[attr-defined]


@pytest.fixture
def run_server(tmp_path, monkeypatch: pytest.MonkeyPatch):
    def _start(client_factory=None) -> dict[str, Any]:
        db_path = tmp_path / "agent.sqlite"
        monkeypatch.setenv("ADGN_AGENT_DB_PATH", str(db_path))
        app = create_app(require_static_assets=True, client_factory=client_factory)
        return start_uvicorn_app(app)

    return _start


def _patch_model(monkeypatch: pytest.MonkeyPatch, create_fn: Callable[[Any], Any]) -> None:
    monkeypatch.setattr(
        "adgn.agent.runtime.container.build_client",
        lambda *a, **k: make_mock(create_fn),
    )


@pytest.mark.integration
def test_policy_proposal_reject_updates_ui(page: Page, run_server, responses_factory):
    """E2E: a policy proposal appears; rejecting it removes it from Open Proposals without reload."""

    state = {"i": 0}

    # First tool call: propose a policy (open proposal). Then end turn.
    async def responses_create(_req):
        i = state["i"]
        state["i"] = i + 1
        if i == 0:
            return responses_factory.make_tool_call(
                "mcp__approval_policy__propose",
                {
                    "policy_python_code": (
                        "TEST_CASES = [(ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ALLOW)]\n"
                        "def decide(ctx):\n    return (PolicyDecision.ASK, 'ask')\n"
                    ),
                    "rationale": "test",
                },
                call_id="call_propose",
            )
        return responses_factory.make_tool_call("mcp__ui__end_turn", {}, call_id="call_ui_end")

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent via helper
    agent_id = api_create_agent(base)

    # Open UI and connect WS
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Trigger proposal creation
    page.locator('textarea[placeholder^="Type a prompt"]').fill("propose policy")
    page.get_by_role("button", name="Send").click()

    # Open proposal should appear in the Approvals tab without reload
    page.get_by_text("Open Proposals (1)").wait_for(timeout=10000)

    # Reject it
    page.get_by_role("button", name="Reject").first.click()

    # The open proposals section should disappear (no open proposals remain)
    # Wait for it to be detached from the DOM
    page.get_by_text("Open Proposals (1)").wait_for(state="detached", timeout=10000)

    s["stop"]()
