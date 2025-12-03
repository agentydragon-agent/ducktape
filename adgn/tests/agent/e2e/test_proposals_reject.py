from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from adgn.mcp.approval_policy.engine import CreateProposalArgs
from adgn.mcp.ui.server import EndTurnInput
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import MakeCall

# Skip if Playwright is not installed
playwright = pytest.importorskip("playwright.sync_api")

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = playwright.Page


async def test_policy_proposal_reject_updates_ui(
    e2e_page, run_server, responses_factory, policy_allow_all: str, make_step_runner
):
    """E2E: a policy proposal appears; rejecting it removes it from Open Proposals without reload."""

    # Mock the agent to create a proposal via tool call, then end turn
    runner = make_step_runner(
        steps=[
            MakeCall("policy_proposer", "create_proposal", CreateProposalArgs(content=policy_allow_all)),
            MakeCall("ui", "end_turn", EndTurnInput()),
        ]
    )
    mock_client = make_mock(runner.handle_request_async)

    s = run_server(lambda model: mock_client)

    e2e_page.goto(s.base_url)
    e2e_page.create_agent_via_ui()

    # Trigger agent to create a proposal by sending a prompt
    e2e_page.send_prompt("create policy proposal")

    # Wait for the run to finish (agent created proposal and ended turn)
    e2e_page.wait_for_text("Status: finished")

    # Reload page to pick up the proposal
    e2e_page.reload_and_reconnect()

    # Open proposal should appear in the Approvals tab
    e2e_page.wait_for_text("Open Proposals (1)")

    # Reject it
    e2e_page.click_reject()

    # The open proposals section should disappear (no open proposals remain)
    e2e_page.page.get_by_text("Open Proposals (1)").wait_for(state="detached", timeout=10000)

    s.stop()
