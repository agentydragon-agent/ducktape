"""Tests for the policy gateway middleware.

These tests verify that the policy gateway correctly gates tool calls based on policy decisions.
"""

import asyncio
import json

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server import FastMCP
import pytest

from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.mcp._shared.constants import (
    PENDING_CALLS_URI,
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_MSG,
)
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.resources import extract_single_text_content
from adgn.mcp.approval_policy.engine import CallDecision


@pytest.mark.requires_docker
async def test_pg_middleware_allow(pg_client):
    # pg_client already has allow-all policy
    res = await pg_client.call_tool(build_mcp_function("backend", "echo"), {"text": "7"})
    assert not res.is_error
    assert res.structured_content == {"echo": "7"}


@pytest.mark.requires_docker
@pytest.mark.parametrize(
    ("decision", "expected_msg"),
    [
        (ApprovalDecision.DENY_ABORT, POLICY_DENIED_ABORT_MSG),
        (ApprovalDecision.DENY_CONTINUE, POLICY_DENIED_CONTINUE_MSG),
    ],
)
async def test_pg_middleware_deny(make_pg_client, make_decision_engine, backend_server, decision, expected_msg):
    engine = make_decision_engine(decision)
    async with make_pg_client({"backend": backend_server}, policy_engine=engine) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "echo"), {"text": "1"})
        assert expected_msg in str(ei.value)


@pytest.mark.requires_docker
async def test_pg_middleware_reserved_backend_code_remap(pg_client):
    with pytest.raises(ToolError) as ei:
        await pg_client.call_tool(build_mcp_function("backend", "raise_reserved"), {})
    # Backend used reserved policy code/message; middleware remaps to explicit misuse error
    assert "policy_backend_reserved_misuse" in str(ei.value)


@pytest.mark.requires_docker
@pytest.mark.xfail(reason="In-proc raises drop ErrorData; stamp not inspectable at middleware layer")
async def test_pg_middleware_backend_stamp_misuse(pg_client):
    with pytest.raises(ToolError) as ei:
        await pg_client.call_tool(build_mcp_function("backend", "raise_with_gateway_stamp"), {})
    assert POLICY_BACKEND_RESERVED_MISUSE_MSG in str(ei.value)


@pytest.mark.requires_docker
async def test_pg_middleware_backend_stamp_misuse_via_proxy(make_pg_client, backend_server):
    # Backend raises an McpError with a spoofed gateway stamp
    # Wrap backend in a FastMCP proxy so downstream errors arrive as result-path
    # CallToolResult (structured ErrorData preserved)
    proxy = FastMCP.as_proxy(backend_server)

    async with make_pg_client({"proxy": proxy}) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("proxy", "raise_with_gateway_stamp"), {})
        s = str(ei.value)
        assert POLICY_BACKEND_RESERVED_MISUSE_MSG in s


@pytest.mark.requires_docker
async def test_pg_middleware_ask_then_allow(make_pg_compositor, make_decision_engine, backend_server):
    """Test ASK decision: tool call blocks until approved via admin server."""
    engine = make_decision_engine(ApprovalDecision.ASK)
    call_ids: list[str] = []

    async with make_pg_compositor({"backend": backend_server}, policy_engine=engine) as (sess, _comp, policy_engine):
        # Start tool call in background - it will block waiting for approval
        call_task = asyncio.create_task(sess.call_tool(build_mcp_function("backend", "echo"), {"text": "3"}))

        # Wait briefly for the call to reach pending state
        await asyncio.sleep(0.2)

        # Read pending calls from the reader server
        async with Client(policy_engine.reader) as reader:
            result = await reader.read_resource(PENDING_CALLS_URI)
            pending_data = json.loads(extract_single_text_content(result))
            pending = pending_data.get("pending", [])
            assert len(pending) > 0, "Expected at least one pending call"
            call_id = pending[0]["call_id"]
            call_ids.append(call_id)

        # Approve via admin server
        async with Client(policy_engine.admin) as admin:
            await admin.call_tool("decide_call", arguments={"call_id": call_id, "decision": CallDecision.APPROVE})

        # Wait for the tool call to complete
        res = await call_task
        assert not res.is_error
        assert call_ids, "pending call should have been recorded"
