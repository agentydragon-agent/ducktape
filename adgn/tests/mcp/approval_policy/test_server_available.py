from __future__ import annotations

from fastmcp.client import Client
import pytest

from adgn.agent.agent import Agent
from adgn.agent.handler import FinishOnTextMessageHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.openai_utils.model import UserMessage
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage


@pytest.mark.requires_docker
async def test_approval_policy_server_is_available(echo_spec, make_pg_compositor, make_step_runner):
    """Test that the approval policy MCP server is available to the agent and lists tools."""

    # make_pg_compositor creates a PolicyEngine with all servers (reader, proposer, admin) already mounted
    servers = dict(echo_spec)
    async with make_pg_compositor(servers) as comp, Client(comp) as mcp_client:
        # Create a sequence where agent lists available tools
        runner = make_step_runner(steps=[AssistantMessage("I can see the approval tools")])
        client = make_mock(runner.handle_request_async)

        # With servers attached, proceed with assertions
        # Check that policy servers are available and list flat tools
        # List tools via a direct Compositor client
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            build_mcp_function(MCPMountPrefix("policy_proposer"), "create_proposal"),
            build_mcp_function(MCPMountPrefix("policy_proposer"), "withdraw_proposal"),
        }
        assert expected <= tool_names

        agent = await Agent.create(
            mcp_client=mcp_client,
            client=client,
            handlers=[FinishOnTextMessageHandler()],
            tool_policy=AllowAnyToolOrTextMessage(),
        )
        agent.insert_message(UserMessage.text("test"))

        # Run should complete without issues
        result = await agent.run()
        assert "approval" in result.text.lower()
