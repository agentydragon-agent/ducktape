import pytest

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.mcp_manager import McpManager
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_manager_resource_subscribe_and_unsubscribe(monkeypatch):
    """McpManager exposes subscribe/unsubscribe; delegate calls hit the session methods.

    Uses the approval_policy server (which exposes resources) as a simple in-proc target.
    """

    server = ApprovalPolicyServer(ApprovalPolicyEngine())
    spec = make_inproc_slot_spec(server)

    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", spec)
        # Realize the slot/session so we can patch the bound methods
        slot = await mcp.ensure_open("approval_policy")

        calls = {"sub": 0, "unsub": 0}

        orig_sub = slot.session.subscribe_resource
        orig_unsub = slot.session.unsubscribe_resource

        async def _sub(uri):
            calls["sub"] += 1
            return await orig_sub(uri)

        async def _unsub(uri):
            calls["unsub"] += 1
            return await orig_unsub(uri)

        monkeypatch.setattr(slot.session, "subscribe_resource", _sub, raising=True)
        monkeypatch.setattr(slot.session, "unsubscribe_resource", _unsub, raising=True)

        uri = "approval-policy://policy.py"

        await mcp.resources_subscribe("approval_policy", uri)
        assert calls["sub"] == 1

        await mcp.resources_unsubscribe("approval_policy", uri)
        assert calls["unsub"] == 1
