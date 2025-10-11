from __future__ import annotations

from pathlib import Path

from hamcrest import assert_that, equal_to, has_length, not_none
import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.server.protocol import Snapshot
from adgn.agent.server.runtime import AgentSession, ConnectionManager
import docker


@pytest.mark.asyncio
async def test_snapshot_surfaces_invalid_proposal(tmp_path: Path) -> None:
    # Arrange: create persistence and persist an invalid proposal
    agent_id = "test-agent-invalid-proposal"
    db_path = tmp_path / "agent.sqlite"
    persistence = SQLitePersistence(str(db_path))
    await persistence.ensure_schema()
    await persistence.create_policy_proposal(
        agent_id, proposal_id="bad1", content="this is not python\n"
    )

    # Build a minimal session with an engine and agent_id so snapshot reads from persistence
    cm = ConnectionManager()
    sess = AgentSession(cm, persistence=persistence)
    sess.agent_id = agent_id
    sess.approval_engine = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id=agent_id,
        persistence=persistence,
        policy_source=load_default_policy_source(),
    )

    # Act
    snap: Snapshot = await sess.build_snapshot()

    # Assert: proposals list exists and includes the proposal id
    assert_that(snap.approval_policy, not_none())
    props = snap.approval_policy.proposals
    assert_that(props, has_length(1))
    p = props[0]
    assert_that(p.id, equal_to("bad1"))
