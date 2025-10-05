from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler, NotificationsHandler
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.openai_utils.model import FakeOpenAIModel
from tests.fixtures.responses import ResponsesFactory


@pytest.mark.asyncio
async def test_resources_list_and_read_policy_and_proposal():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    async with McpManager({}) as mcp:
        await mcp.attach_server(
            "approval_policy",
            make_inproc_slot_spec(server, init_timeout_secs=2),
        )
        # Open session and create one proposal to surface as a resource
        await mcp.get_session("approval_policy")
        engine.set_policy(
            """
from adgn.agent.approvals import PolicyDecision, WellKnownServers, WellKnownTools, ApprovalContext
TEST_CASES = [
  (ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ALLOW),
]
def decide(ctx):
    return (PolicyDecision.ALLOW, 'ok')
"""
        )
        pid = engine.create_proposal(
            source=(
                "TEST_CASES = [(ApprovalContext(server=WellKnownServers.UI, tool=WellKnownTools.SEND_MESSAGE, arguments={}), PolicyDecision.ALLOW)]\n"
                "def decide(ctx):\n    return (PolicyDecision.ASK, 'ask')\n"
            )
        )

        # List resources directly via McpManager
        items = await mcp.list_resources(only=["approval_policy"])
        uris = {str(it.resource.uri) for it in items if it.resource.uri}
        assert "approval-policy://policy.py" in uris
        assert f"approval-policy://proposals/{pid}.json" in uris

        # Read policy.py directly via server (ApprovalPolicyServer.read_resource returns raw text)
        r = await mcp.read_resource("approval_policy", "approval-policy://policy.py")
        text = ""
        for part in getattr(r, "contents", None) or []:
            try:
                text = part.text  # type: ignore[attr-defined]
                break
            except Exception:
                continue
        assert isinstance(text, str)
        assert "def decide(" in text

        # Smoke: run a tiny agent turn and ensure nothing crashes while resources server is present
        rf = ResponsesFactory("gpt-5-nano")
        client = FakeOpenAIModel([rf.make_assistant_message("ok")])

        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            handlers=[NotificationsHandler(mcp), AutoHandler()],
            client=client,
            system="n/a",
        )
        await agent.run("hello")
        # If we reached here without exceptions, discovery/read paths are wired correctly
