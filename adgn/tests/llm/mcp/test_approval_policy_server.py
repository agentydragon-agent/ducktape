from __future__ import annotations

import pytest

from adgn.llm.mini_codex.aggregating_handler import NotificationsHandler, AutoHandler
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine
from adgn.llm.openai_utils.model import FakeOpenAIModel


@pytest.mark.asyncio
async def test_resources_list_and_read_policy_and_proposal():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    specs = {"approval_policy": make_inproc_slot_spec(server)}

    async with McpManager(specs) as mcp:
        # Open session and create one proposal to surface as a resource
        await mcp.get_session("approval_policy")
        engine.set_policy("def decide(ctx):\n    return 'allow'\n")
        pid = engine.create_proposal(source="def decide(ctx):\n    return 'ask'\n")

        # List resources directly via McpManager
        items = await mcp.list_resources(only=["approval_policy"])
        uris = {it["uri"] for it in items}
        assert "approval-policy://policy.py" in uris
        assert f"approval-policy://proposals/{pid}.json" in uris

        # Read policy.py directly via manager (server.read_resource); avoid tool wrapper shape differences
        r = await mcp.read_resource("approval_policy", "approval-policy://policy.py")
        # Normalize into dict form
        if hasattr(r, "model_dump"):
            r = r.model_dump()
        contents = (
            r.get("contents", [])
            if isinstance(r, dict)
            else (r[0] if isinstance(r, tuple) else [])
        )
        assert contents and (contents[0].get("text") or "").startswith("def decide(")

        # Smoke: run a tiny agent turn and ensure nothing crashes while resources server is present
        from tests.fixtures.responses import ResponsesFactory

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
