"""Integration test to verify approval system is wired correctly."""

import asyncio

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import (
    ApprovalHub,
    ApprovalPolicyEngine,
)
from adgn.agent.handler import ContinueDecision
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler
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
    engine.set_policy(
        """
from adgn.agent.approvals import PolicyDecision, WellKnownServers, WellKnownTools, ApprovalContext
TEST_CASES = [
  (ApprovalContext(server="echo", tool="echo", arguments={}), PolicyDecision.ASK),
]
def decide(ctx):
    return (PolicyDecision.ASK, "Always ask for approval")
"""
    )

    # Create a fake response that tries to call a tool
    seq = [
        responses_factory.make(
            responses_factory.tool_call("mcp__echo__echo", {"text": "test"}),
        ),
        responses_factory.make_assistant_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager({}) as mcp:
        echo_specs = make_echo_spec()
        # attach echo server runtime slot spec
        for name, slot in echo_specs.items():
            await mcp.attach_server(name, slot)
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


# Note: server availability and resources are tested under tests/mcp/approval_policy
