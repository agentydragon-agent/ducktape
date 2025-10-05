"""Test that approval policy MCP server exposes proper tool schemas."""

import asyncio
import json

import pytest

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.mcp_manager import McpManager, build_mcp_function
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_approval_policy_tool_schemas():
    """Verify that approval policy server exposes proper tool schemas, not generic wrappers."""

    # Create the approval policy server
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)

    # Create MCP manager with the server
    async with McpManager({}) as mcp:
        await mcp.attach_server(
            "approval_policy",
            make_inproc_slot_spec(server, init_timeout_secs=2),
        )
        # List tools from the server
        tools = await mcp.list_tools(["approval_policy"])

        # Find the specific tools
        propose_tool = None
        withdraw_tool = None
        get_status_tool = None

        for tool in tools:
            full_name = build_mcp_function(tool.server, tool.tool.name)
            if full_name == "mcp__approval_policy__propose":
                propose_tool = tool
            elif full_name == "mcp__approval_policy__withdraw":
                withdraw_tool = tool
            elif full_name == "mcp__approval_policy__get_status":
                get_status_tool = tool

        # Verify all tools are found
        assert propose_tool is not None, "propose tool not found"
        assert withdraw_tool is not None, "withdraw tool not found"
        assert get_status_tool is not None, "get_status tool not found"

        # Check propose tool schema
        propose_params = propose_tool.tool.inputSchema or {}
        print("Propose tool parameters:", json.dumps(propose_params, indent=2))

        # The schema should have proper parameter names, not _wrappedArguments
        assert "properties" in propose_params
        props = propose_params["properties"]

        # Check for the actual bug - if we see _wrappedArguments, that's wrong
        if "a" in props and "kw" in props:
            # This is the bug - generic wrapper arguments
            assert False, f"Tool has generic wrapper arguments: {list(props.keys())}"

        # Should have proper parameters (renamed: source -> policy_python_code) or patch_unified
        assert "policy_python_code" in props, (
            f"Missing 'policy_python_code' parameter. Got: {list(props.keys())}"
        )
        assert "patch_unified" in props, (
            f"Missing 'patch_unified' parameter. Got: {list(props.keys())}"
        )
        assert "rationale" in props, f"Missing 'rationale' parameter. Got: {list(props.keys())}"

        # And the schema should clearly describe the requirements on the Python source
        desc = props["policy_python_code"].get("description", "")
        assert "Full Python source" in desc and "decide(ctx)" in desc and "TEST_CASES" in desc
        # Patch field should mention unified diff and include an example
        pdesc = props["patch_unified"].get("description", "")
        assert "Unified diff patch" in pdesc and "@@" in pdesc

        # Check withdraw tool schema
        withdraw_params = withdraw_tool.tool.inputSchema or {}
        print("Withdraw tool parameters:", json.dumps(withdraw_params, indent=2))

        props = withdraw_params.get("properties", {})
        if "a" in props and "kw" in props:
            assert False, f"Withdraw tool has generic wrapper arguments: {list(props.keys())}"

        assert "proposal_id" in props, f"Missing 'proposal_id' parameter. Got: {list(props.keys())}"

        # Check get_status tool schema
        status_params = get_status_tool.tool.inputSchema or {}
        print("Get_status tool parameters:", json.dumps(status_params, indent=2))

        # get_status should have no required parameters or empty schema
        props = status_params.get("properties", {})
        if "a" in props and "kw" in props:
            assert False, f"get_status tool has generic wrapper arguments: {list(props.keys())}"


if __name__ == "__main__":
    asyncio.run(test_approval_policy_tool_schemas())
