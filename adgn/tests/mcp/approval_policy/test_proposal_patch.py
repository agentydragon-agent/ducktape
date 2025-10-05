from __future__ import annotations

from mcp import types as mcp_types
import pytest

from adgn.agent.approvals import (
    ApprovalContext,
    ApprovalPolicyEngine,
    WellKnownServers,
    WellKnownTools,
)
from adgn.agent.mcp_manager import McpManager
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_propose_via_patch_applies_and_opens_proposal():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    # Create a minimal unified patch that inserts a comment at the top
    patch = """@@ -1,0 +1,1 @@\n+# Policy header (patched)\n"""

    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        # Propose via patch
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"patch_unified": patch, "rationale": "add comment"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        pid = (res.structuredContent or {}).get("proposal_id")
        assert pid, res
        # Status should list the open proposal
        status: mcp_types.CallToolResult = await mcp.call_tool("approval_policy", "get_status", {})
        assert isinstance(status, mcp_types.CallToolResult)
        sdict = status.structuredContent or {}
        proposals = sdict.get("proposals", [])
        assert any(p.get("id") == pid and p.get("status") == "open" for p in proposals)


@pytest.mark.asyncio
async def test_propose_requires_one_of_source_or_patch():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        # Neither provided should be an error result
        res1: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy", "propose", {"rationale": "x"}
        )
        assert isinstance(res1, mcp_types.CallToolResult)
        assert res1.isError is True
        # Both provided should be an error result
        res2: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {
                "patch_unified": "@@ -1,0 +1,1 @@\n+# x\n",
                "policy_python_code": "print('x')\n",
                "rationale": "x",
            },
        )
        assert isinstance(res2, mcp_types.CallToolResult)
        assert res2.isError is True


@pytest.mark.asyncio
async def test_propose_via_patch_invalid_rejected():
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    # Malformed patch header -> should return a tool error
    bad_patch = "@@ nonsense @@\n+foo\n"
    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"patch_unified": bad_patch, "rationale": "bad"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        assert res.isError is True


@pytest.mark.asyncio
async def test_propose_patch_without_hunks_rejected():
    """Patch missing any @@ hunk header should be rejected."""
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    # Patch text that lacks a proper unified-diff hunk header
    no_hunks_patch = "# not a unified diff patch\n+line without header\n"
    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"patch_unified": no_hunks_patch, "rationale": "no hunks"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        assert res.isError is True


@pytest.mark.asyncio
async def test_propose_patch_no_change_rejected():
    """A patch with only context lines (no +/-) that produces no change is rejected."""
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    current_src, _ = engine.get_policy()
    first_line = current_src.splitlines()[0] if current_src.splitlines() else ""
    # Build a unified hunk that only includes the first line as context, no modifications
    no_change_patch = f"@@ -1,1 +1,1 @@\n {first_line}\n"
    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"patch_unified": no_change_patch, "rationale": "no change"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        assert res.isError is True


@pytest.mark.asyncio
async def test_proposal_approve_applies_policy_allows_sandbox_exec():
    """Propose new policy via source, approve it, and verify behavior changes."""
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)
    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))

        # Minimal policy: allow seatbelt sandbox_exec, ask otherwise; include a simple TEST_CASES
        policy_src = (
            "TEST_CASES = ["
            "(ApprovalContext(server=WellKnownServers.SEATBELT_EXEC, tool=WellKnownTools.SANDBOX_EXEC, arguments={}), PolicyDecision.ALLOW)"
            "]\n"
            "def decide(ctx):\n"
            "    if ctx.server == WellKnownServers.SEATBELT_EXEC and ctx.tool == WellKnownTools.SANDBOX_EXEC:\n"
            "        return (PolicyDecision.ALLOW, 'allow seatbelt exec')\n"
            "    return (PolicyDecision.ASK, 'ask')\n"
        )

        # Open a proposal using full source (compile-only validation at propose time)
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"policy_python_code": policy_src, "rationale": "allow sandbox exec"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        pid = (res.structuredContent or {}).get("proposal_id")
        assert pid, res

        # Engine initially asks for sandbox exec with default policy
        assert (
            engine.decide(
                ApprovalContext(
                    server=WellKnownServers.SEATBELT_EXEC,
                    tool=WellKnownTools.SANDBOX_EXEC,
                    arguments={},
                )
            )
            == "ask"
        )

        # Approve the proposal (engine.apply validates tests and loads policy)
        engine.apply(pid, "approve")

        # After approval, the decision should reflect the new policy (allow)
        assert (
            engine.decide(
                ApprovalContext(
                    server=WellKnownServers.SEATBELT_EXEC,
                    tool=WellKnownTools.SANDBOX_EXEC,
                    arguments={},
                )
            )
            == "allow"
        )

        # Status now shows the proposal as approved
        st = engine.get_status()
        assert any(p.id == pid and p.status == "approved" for p in st.proposals)


@pytest.mark.asyncio
async def test_proposal_patch_approve_applies_and_changes_behavior():
    """Propose a patch that overrides decide() to allow sandbox_exec; approve and verify."""
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)

    # Patch that appends a new decide() at the end of policy.py, preserving original semantics
    # and allowing seatbelt sandbox_exec. Using a large hunk start appends additions.
    patch = """
@@ -999999,0 +999999,11 @@
+def decide(ctx):
+    if ctx.server == WellKnownServers.UI and ctx.tool in (WellKnownTools.SEND_MESSAGE, WellKnownTools.END_TURN):
+        return (PolicyDecision.ALLOW, "UI communication")
+    if ctx.server == WellKnownServers.APPROVAL_POLICY and ctx.tool in (WellKnownTools.GET_STATUS, WellKnownTools.PROPOSE, WellKnownTools.WITHDRAW):
+        return (PolicyDecision.ALLOW, "Approval management")
+    if ctx.server == WellKnownServers.RESOURCES:
+        return (PolicyDecision.ALLOW, "Resource operations allowed")
+    if ctx.server == WellKnownServers.SEATBELT_EXEC and ctx.tool == WellKnownTools.SANDBOX_EXEC:
+        return (PolicyDecision.ALLOW, "allow seatbelt exec")
+    return (PolicyDecision.ASK, "ask")
"""

    async with McpManager({}) as mcp:
        await mcp.attach_server("approval_policy", make_inproc_slot_spec(server))
        # Propose via patch
        res: mcp_types.CallToolResult = await mcp.call_tool(
            "approval_policy",
            "propose",
            {"patch_unified": patch, "rationale": "allow sandbox exec via patch"},
        )
        assert isinstance(res, mcp_types.CallToolResult)
        pid = (res.structuredContent or {}).get("proposal_id")
        assert pid, res

        # Before approval: default policy asks
        assert (
            engine.decide(
                ApprovalContext(
                    server=WellKnownServers.SEATBELT_EXEC,
                    tool=WellKnownTools.SANDBOX_EXEC,
                    arguments={},
                )
            )
            == "ask"
        )

        # Approve (engine validates tests on apply via set_policy)
        engine.apply(pid, "approve")

        # After approval: decision should be allow per patched decide()
        assert (
            engine.decide(
                ApprovalContext(
                    server=WellKnownServers.SEATBELT_EXEC,
                    tool=WellKnownTools.SANDBOX_EXEC,
                    arguments={},
                )
            )
            == "allow"
        )
