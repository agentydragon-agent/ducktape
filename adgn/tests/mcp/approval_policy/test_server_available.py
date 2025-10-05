from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.mcp_manager import McpManager, build_mcp_function
from adgn.agent.reducer import AutoHandler
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.openai_utils.model import FakeOpenAIModel


@pytest.mark.asyncio
async def test_approval_policy_server_is_available(responses_factory, make_echo_spec):
    """Test that the approval policy MCP server is available to the agent and lists tools."""

    # Create approval components
    engine = ApprovalPolicyEngine()
    hub = ApprovalHub()

    # Add approval server to specs
    approval_server = ApprovalPolicyServer(engine)
    echo_specs = make_echo_spec()
    async with McpManager({}) as mcp:
        for name, slot in echo_specs.items():
            await mcp.attach_server(name, slot)
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(approval_server))

        # Create a sequence where agent lists available tools
        seq = [responses_factory.make_assistant_message("I can see the approval tools")]
        client = FakeOpenAIModel(seq)

        # With servers attached, proceed with assertions
        # Check that approval_policy server is available by listing its tools
        tools = await mcp.list_tools(only=["approval_policy"])
        assert tools, "approval_policy server should list tools"

        # List tools from the approval server
        tool_names = [build_mcp_function(t.server, t.tool.name) for t in tools]

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
