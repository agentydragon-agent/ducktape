"""Integration test to verify approval system is wired correctly."""

import asyncio
import json

from fastmcp.client import Client
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp._shared.constants import PENDING_CALLS_URI
from adgn.mcp.approval_policy.engine import CallDecision
from adgn.mcp.testing.simple_servers import EchoInput
from tests.agent.testdata.approval_policy import make_policy
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, MakeCall


@pytest.mark.requires_docker
async def test_approval_system_wired_and_blocks_on_ask(
    responses_factory, echo_spec, make_pg_compositor, make_approval_policy_server, make_step_runner
) -> None:
    """Test that the approval system is properly wired and blocks tool calls via middleware."""

    # Prepare approval engine with an ASK policy for echo.echo using shared factory
    engine = make_approval_policy_server(
        make_policy(decision_expr="PolicyDecision.ASK", server="echo", tool="echo", default="ask")
    )

    # Model tries to call the tool then returns text
    mock = make_step_runner(steps=[MakeCall("echo", "echo", EchoInput(text="test")), AssistantMessage("done")])
    client = make_mock(mock.handle_request_async)

    # Use make_pg_compositor with custom policy engine
    servers = dict(echo_spec)
    async with make_pg_compositor(servers, policy_engine=engine) as (mcp_client, _comp, policy_engine):
        agent = await MiniCodex.create(
            mcp_client=mcp_client, system="test", client=client, handlers=[BaseHandler()], tool_policy=RequireAnyTool()
        )

        # Start the agent run in the background
        run_task = asyncio.create_task(agent.run("test"))

        # Wait briefly for the agent to hit the approval block
        # Read pending://calls resource from reader server via MCP
        async with Client(policy_engine.reader) as reader_client:
            for _ in range(20):  # up to ~1s
                result = await reader_client.read_resource(PENDING_CALLS_URI)
                content = result.contents[0].text if result.contents else "{}"
                pending_data = json.loads(content)
                pending = pending_data.get("pending", [])
                if len(pending) >= 1:
                    break
                await asyncio.sleep(0.05)

            assert len(pending) == 1, f"Expected 1 pending approval, got {len(pending)}"

            # Get the call_id from the pending approval
            call_id = pending[0]["call_id"]

        # Approve the tool call via admin server's decide_call tool
        async with Client(policy_engine.admin) as admin_client:
            await admin_client.call_tool(
                "decide_call", arguments={"call_id": call_id, "decision": CallDecision.APPROVE}
            )
        result = await run_task
        assert result.text.strip() == "done"


# Note: server availability and resources are tested under tests/mcp/approval_policy
