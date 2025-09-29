"""Test that approval policy MCP server exposes proper tool schemas."""

import asyncio
import json
from typing import Any

import pytest

from adgn.llm.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_approval_policy_tool_schemas():
    """Verify that approval policy server exposes proper tool schemas, not generic wrappers."""

    # Create the approval policy server
    engine = ApprovalPolicyEngine()
    server = ApprovalPolicyServer(engine)

    # Create MCP manager with the server
    specs = {
        "approval_policy": make_inproc_slot_spec(server)
    }

    async with McpManager(specs) as mcp:
        # List tools from the server
        tools = await mcp.list_tools(["approval_policy"])

        # Find the specific tools
        propose_tool = None
        withdraw_tool = None
        get_status_tool = None

        for tool in tools:
            if tool["name"] == "mcp__approval_policy__propose":
                propose_tool = tool
            elif tool["name"] == "mcp__approval_policy__withdraw":
                withdraw_tool = tool
            elif tool["name"] == "mcp__approval_policy__get_status":
                get_status_tool = tool

        # Verify all tools are found
        assert propose_tool is not None, "propose tool not found"
        assert withdraw_tool is not None, "withdraw tool not found"
        assert get_status_tool is not None, "get_status tool not found"

        # Check propose tool schema
        propose_params = propose_tool.get("parameters", {})
        print("Propose tool parameters:", json.dumps(propose_params, indent=2))

        # The schema should have proper parameter names, not _wrappedArguments
        assert "properties" in propose_params
        props = propose_params["properties"]

        # Check for the actual bug - if we see _wrappedArguments, that's wrong
        if "a" in props and "kw" in props:
            # This is the bug - generic wrapper arguments
            assert False, f"Tool has generic wrapper arguments: {list(props.keys())}"

        # Should have proper parameters
        assert "source" in props, f"Missing 'source' parameter. Got: {list(props.keys())}"
        assert "rationale" in props, f"Missing 'rationale' parameter. Got: {list(props.keys())}"

        # Check withdraw tool schema
        withdraw_params = withdraw_tool.get("parameters", {})
        print("Withdraw tool parameters:", json.dumps(withdraw_params, indent=2))

        props = withdraw_params.get("properties", {})
        if "a" in props and "kw" in props:
            assert False, f"Withdraw tool has generic wrapper arguments: {list(props.keys())}"

        assert "proposal_id" in props, f"Missing 'proposal_id' parameter. Got: {list(props.keys())}"

        # Check get_status tool schema
        status_params = get_status_tool.get("parameters", {})
        print("Get_status tool parameters:", json.dumps(status_params, indent=2))

        # get_status should have no required parameters or empty schema
        props = status_params.get("properties", {})
        if "a" in props and "kw" in props:
            assert False, f"get_status tool has generic wrapper arguments: {list(props.keys())}"


if __name__ == "__main__":
    asyncio.run(test_approval_policy_tool_schemas())