from __future__ import annotations

from fastmcp.mcp_config import MCPConfig
from hamcrest import assert_that, equal_to, has_length, not_none

from adgn.agent.approvals import load_default_policy_source
from adgn.agent.persist import AgentMetadata
from adgn.agent.server.protocol import Snapshot
from adgn.agent.server.runtime import AgentSession, ConnectionManager
from adgn.mcp.approval_policy.engine import PolicyEngine


async def test_snapshot_surfaces_invalid_proposal(docker_client, sqlite_persistence) -> None:
    # Arrange: create persistence and persist an invalid proposal
    agent_id = await sqlite_persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="tests"))
    await sqlite_persistence.create_policy_proposal(agent_id, proposal_id="bad1", content="this is not python\n")

    # Build a minimal session with an engine and agent_id so snapshot reads from persistence
    cm = ConnectionManager()
    approval_engine = PolicyEngine(
        docker_client=docker_client,
        agent_id=agent_id,
        persistence=sqlite_persistence,
        policy_source=load_default_policy_source(),
    )
    sess = AgentSession(cm, persistence=sqlite_persistence, agent_id=agent_id, approval_engine=approval_engine)

    # Act
    snap: Snapshot = await sess.build_snapshot()

    # Assert: proposals list exists and includes the proposal id
    assert_that(snap.approval_policy, not_none())
    policy = snap.approval_policy
    assert policy is not None, "approval_policy should not be None"
    props = policy.proposals
    assert_that(props, has_length(1))
    p = props[0]
    assert_that(p.id, equal_to("bad1"))
