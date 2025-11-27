from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function
from tests.llm.support.openai_mock import FakeOpenAIModel


@pytest.mark.requires_docker
async def test_approval_policy_server_is_available(responses_factory, make_echo_spec, make_pg_compositor):
    """Test that the approval policy MCP server is available to the agent and lists tools."""

    # make_pg_compositor creates a PolicyEngine with reader auto-mounted;
    # we just need to mount the proposer separately
    servers = dict(make_echo_spec())
    async with make_pg_compositor(servers) as (mcp_client, comp, policy_engine):
        # Mount the proposer server under the new naming scheme
        await comp.mount_inproc("policy_proposer", policy_engine.policy_proposer)

        # Create a sequence where agent lists available tools
        seq = [responses_factory.make_assistant_message("I can see the approval tools")]
        client = FakeOpenAIModel(seq)

        # With servers attached, proceed with assertions
        # Check that policy servers are available and list flat tools
        # List tools via a direct Compositor client
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            build_mcp_function("policy_proposer", "create_proposal"),
            build_mcp_function("policy_proposer", "withdraw_proposal"),
        }
        assert expected <= tool_names

        agent = await MiniCodex.create(
            model=responses_factory.model, mcp_client=mcp_client, system="test", client=client, handlers=[AutoHandler()]
        )

        # Run should complete without issues
        result = await agent.run("test")
        assert "approval" in result.text.lower()
