"""Integration test to verify approval system is wired correctly."""

import asyncio
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.agent.approvals import (
    ApprovalHub,
    ApprovalPolicyEngine,
)
from adgn.agent.handler import ContinueDecision
from adgn.agent.mcp_manager import McpManager
from adgn.openai_utils.model import FakeOpenAIModel


@pytest.mark.asyncio
async def test_approval_system_wired_and_blocks_on_ask(
    responses_factory,
    make_echo_spec,
):
    """Test that the approval system is properly wired and blocks tool calls."""

    # Create approval components
    engine = ApprovalPolicyEngine()
    hub = ApprovalHub()

    # Set a policy that always asks for approval
    engine.set_policy("""
def decide(ctx: dict) -> str:
    return "ask"  # Always ask for approval
""")

    # Create a fake response that tries to call a tool
    seq = [
        responses_factory.make(
            responses_factory.tool_call("mcp__echo__echo", {"text": "test"}),
        ),
        responses_factory.make_assistant_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    specs = make_echo_spec()

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
            approval_engine=engine,
            approval_hub=hub,
        )

        # Start the agent run in the background
        run_task = asyncio.create_task(agent.run("test"))

        # Wait briefly for the agent to hit the approval block
        for _ in range(20):  # up to ~1s
            if len(hub._requests) >= 1:
                break
            await asyncio.sleep(0.05)
        pending = hub._requests
        assert len(pending) == 1, f"Expected 1 pending approval, got {len(pending)}"

        # Get the call_id from the pending approval
        call_id = list(pending.keys())[0]

        # Approve the tool call
        hub.resolve(call_id, ContinueDecision())

        # The agent should now complete
        result = await run_task
        assert result.text.strip() == "done"


@pytest.mark.asyncio
async def test_approval_policy_server_is_available(
    responses_factory,
    make_echo_spec,
):
    """Test that the approval policy MCP server is available to the agent."""

    from adgn.mcp.approval_policy.server import ApprovalPolicyServer
    from adgn.mcp.inproc_transport import make_inproc_slot_spec

    # Create approval components
    engine = ApprovalPolicyEngine()
    hub = ApprovalHub()

    # Add approval server to specs
    approval_server = ApprovalPolicyServer(engine)
    specs = make_echo_spec()
    specs["approval_policy"] = make_inproc_slot_spec(approval_server)

    # Create a sequence where agent lists available tools
    seq = [
        responses_factory.make_assistant_message("I can see the approval tools"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager(specs) as mcp:
        # Check that approval_policy server is available
        assert "approval_policy" in mcp.server_names

        # List tools from the approval server
        tools = await mcp.list_tools(only=["approval_policy"])
        tool_names = [t["name"] for t in tools]

        # Verify the approval policy tools are available
        assert "mcp__approval_policy__propose" in tool_names
        assert "mcp__approval_policy__withdraw" in tool_names
        assert "mcp__approval_policy__get_status" in tool_names
        # Note: apply should NOT be exposed as a tool to the LLM
        assert "mcp__approval_policy__apply" not in tool_names

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
            approval_engine=engine,
            approval_hub=hub,
        )

        # Run should complete without issues
        result = await agent.run("test")
        assert "approval" in result.text.lower()
