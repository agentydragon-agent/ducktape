from __future__ import annotations

import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.mcp._shared.constants import APPROVAL_POLICY_RESOURCE_URI
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
import docker


@pytest.mark.asyncio
async def test_resources_list_and_read_policy(make_typed_mcp):
    """List and read resources directly from the server without a compositor."""
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    engine = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="tests",
        persistence=p,
        policy_source=load_default_policy_source(),
    )
    server = ApprovalPolicyServer(engine)

    async with make_typed_mcp(server, "approval_policy") as (client, _sess):
        # Approval policy server exposes a single canonical resource for the active policy
        items = await client.list_resources()
        assert isinstance(items, list)
        # Only the approval policy server is present, so exactly one resource
        assert len(items) == 1
        it = items[0]
        assert str(it.uri) == str(APPROVAL_POLICY_RESOURCE_URI)
        assert it.name == "policy.py"
        assert it.mimeType == "text/x-python"

        # Read the resource content and ensure it contains the policy class
        contents = await client.read_resource(str(APPROVAL_POLICY_RESOURCE_URI))
        text_parts = [p for p in contents if getattr(p, "mimeType", None) == "text/x-python"]
        assert any("class ApprovalPolicy" in getattr(p, "text", "") for p in text_parts)
