from __future__ import annotations

from typing import Any, Callable

import pytest

from adgn.agent.server.app import create_app
from adgn.mcp._shared.naming import build_mcp_function
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
@pytest.mark.asyncio
async def test_policy_proposal_reject_updates_ui(
    page: Page, run_server, responses_factory, policy_allow_all: str, sqlite_persistence
):
    """E2E: a policy proposal appears; rejecting it removes it from Open Proposals without reload."""

    # No model tool calls needed for proposal authoring in this flow
    async def responses_create(_req):
        return responses_factory.make_tool_call(
            build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end"
        )

    s = run_server(lambda model: make_mock(responses_create))
    base = s["base_url"]

    # Create agent via helper
    agent_id = api_create_agent(base)

    # Open UI and connect WS
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Create a proposal directly via persistence (no named volumes)
    # Insert a proposal for this agent
    await sqlite_persistence.create_policy_proposal(agent_id, "p-e2e", policy_allow_all)
    # Open UI and connect WS
    page.goto(base + f"/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=10000)

    # Open proposal should appear in the Approvals tab without reload
    page.get_by_text("Open Proposals (1)").wait_for(timeout=10000)

    # Reject it
    page.get_by_role("button", name="Reject").first.click()

    # The open proposals section should disappear (no open proposals remain)
    # Wait for it to be detached from the DOM
    page.get_by_text("Open Proposals (1)").wait_for(state="detached", timeout=10000)

    s["stop"]()
