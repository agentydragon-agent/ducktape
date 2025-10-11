from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.openai_utils.model import FakeOpenAIModel
import docker


@pytest.mark.asyncio
async def test_approval_policy_server_is_available(
    responses_factory, make_echo_spec, make_pg_compositor
):
    """Test that the approval policy MCP server is available to the agent and lists tools."""

    # Create approval components
    # Engine with required context
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    engine = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=p,
        policy_source=load_default_policy_source(),
    )

    # Add approval server to specs
    reader = ApprovalPolicyServer(engine)
    from adgn.mcp.approval_policy.server import ApprovalPolicyProposerServer

    proposer = ApprovalPolicyProposerServer(
        engine=engine,
        readonly=reader,
        agent_id=engine.agent_id,
        persistence=engine.persistence,
        docker_client=engine.docker_client,
    )
    echo_specs = make_echo_spec()
    servers = echo_specs()
    servers["approval_policy"] = reader
    servers["approval_policy.proposer"] = proposer
    async with make_pg_compositor(servers) as (mcp_client, _comp):
        # Create a sequence where agent lists available tools
        seq = [responses_factory.make_assistant_message("I can see the approval tools")]
        client = FakeOpenAIModel(seq)

        # With servers attached, proceed with assertions
        # Check that approval_policy server is available and lists flat tools
        # List tools via a direct Compositor client
        tools = await mcp_client.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            build_mcp_function("approval_policy.proposer", "create_proposal"),
            build_mcp_function("approval_policy.proposer", "withdraw_proposal"),
        }
        assert expected <= tool_names

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp_client=mcp_client,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )

        # Run should complete without issues
        result = await agent.run("test")
        assert "approval" in result.text.lower()
