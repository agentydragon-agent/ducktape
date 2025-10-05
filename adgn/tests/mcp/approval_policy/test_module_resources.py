from mcp import types as mcp_types
import pytest

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.mcp_manager import McpManager
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_module_scheme_lists_and_reads_sources():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    async with McpManager({}) as mcp:
        await mcp.attach_server(
            "approval_policy",
            make_inproc_slot_spec(server, init_timeout_secs=2),
        )
        # List resources for approval_policy
        items = await mcp.list_resources(only=["approval_policy"])
        uris = [str(it.resource.uri) for it in items]
        # Expect module:// URIs for approvals and seatbelt model
        assert "module://adgn/agent/approvals.py" in uris
        assert "module://adgn/seatbelt/model.py" in uris
        # Read both sources; content should be non-empty text/plain
        for uri in ("module://adgn/agent/approvals.py", "module://adgn/seatbelt/model.py"):
            res = await mcp.read_resource("approval_policy", uri)
            assert res.contents, f"no contents for {uri}"
            part0 = res.contents[0]
            if isinstance(part0, mcp_types.TextResourceContents):
                assert isinstance(part0.text, str) and len(part0.text) > 0
            elif isinstance(part0, mcp_types.BlobResourceContents):
                assert isinstance(part0.blob, str) and len(part0.blob) > 0
            else:
                raise AssertionError(f"unexpected content type: {type(part0).__name__}")
