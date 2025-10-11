"""Test that approval policy MCP server exposes proper tool schemas."""

import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.mcp.approval_policy.server import ApprovalPolicyProposerServer, ApprovalPolicyServer
import docker


@pytest.mark.asyncio
async def test_approval_policy_tool_schemas(make_typed_mcp):
    """Verify approval_policy tools are exposed with flat typed schemas."""

    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    engine = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=p,
        policy_source=load_default_policy_source(),
    )
    reader = ApprovalPolicyServer(engine)
    proposer = ApprovalPolicyProposerServer(
        engine=engine,
        readonly=reader,
        agent_id=engine.agent_id,
        persistence=engine.persistence,
        docker_client=engine.docker_client,
    )

    async with make_typed_mcp(proposer, "approval_policy.proposer") as (client, _sess):
        # Expect typed tools available
        names = set(client.models.keys())
        assert {"create_proposal", "withdraw_proposal"} <= names
