"""Integration test to verify approval system is wired correctly."""

import asyncio

from fastmcp.client import Client
import pytest

from adgn.agent.agent import Agent
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp.approval_policy.engine import CallDecision, PendingCallsResponse
from adgn.openai_utils.model import SystemMessage
from tests.agent.testdata.approval_policy import make_policy
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, EchoCall


@pytest.mark.requires_docker
async def test_approval_system_wired_and_blocks_on_ask(
    responses_factory, echo_spec, make_pg_compositor, make_approval_policy_server, make_step_runner
) -> None:
    """Test that the approval system is properly wired and blocks tool calls via middleware."""

    # Prepare approval engine with an ASK policy for echo.echo using shared factory
    engine = await make_approval_policy_server(
        make_policy(decision_expr="PolicyDecision.ASK", server="echo", tool="echo", default=ApprovalDecision.ASK)
    )

    # Model tries to call the tool then returns text
    mock = make_step_runner(steps=[EchoCall("test"), AssistantMessage("done")])
    client = make_mock(mock.handle_request_async)

    # Use make_pg_compositor with custom policy engine
    servers = dict(echo_spec)
    async with make_pg_compositor(servers, policy_engine=engine) as comp:
        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client, client=client, handlers=[BaseHandler()], tool_policy=RequireAnyTool()
            )
            agent.insert_message(SystemMessage.text("test"))

            # Start the agent run in the background
            run_task = asyncio.create_task(agent.run())

        # Wait briefly for the agent to hit the approval block
        # Read pending://calls resource from reader server via MCP
        async with Client(comp.approval_engine.reader) as reader_client:
            pending_data: PendingCallsResponse
            for _ in range(20):  # up to ~1s
                pending_data = await read_text_json_typed(
                    reader_client, comp.approval_engine.reader.pending_calls_resource.uri, PendingCallsResponse
                )
                if len(pending_data.pending) >= 1:
                    break
                await asyncio.sleep(0.05)

            assert len(pending_data.pending) == 1, f"Expected 1 pending approval, got {len(pending_data.pending)}"

            # Get the call_id from the pending approval
            call_id = pending_data.pending[0].call_id

        # Approve the tool call via admin server's decide_call tool
        async with Client(comp.approval_engine.admin) as admin_client:
            await admin_client.call_tool(
                "decide_call", arguments={"call_id": call_id, "decision": CallDecision.APPROVE}
            )
        result = await run_task
        assert result.text.strip() == "done"


# Note: server availability and resources are tested under tests/mcp/approval_policy
