import asyncio

from fastmcp.exceptions import ToolError
from fastmcp.server import FastMCP
import pytest

from adgn.agent.handler import ContinueDecision
from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.mcp._shared.constants import (
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_MSG,
)
from adgn.mcp._shared.naming import build_mcp_function


@pytest.mark.requires_docker
async def test_pg_middleware_allow(make_pg_session_with_decision):
    async with make_pg_session_with_decision(ApprovalDecision.ALLOW) as sess:
        res = await sess.call_tool(build_mcp_function("backend", "echo"), {"text": "7"})
        # fastmcp Client returns a wrapper with is_error
        assert not getattr(res, "is_error", False)
        assert getattr(res, "structured_content", None) == {"echo": "7"}


@pytest.mark.requires_docker
async def test_pg_middleware_deny_abort(make_pg_session_with_decision):
    async with make_pg_session_with_decision(ApprovalDecision.DENY_ABORT) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "echo"), {"text": "1"})
        assert POLICY_DENIED_ABORT_MSG in str(ei.value)


@pytest.mark.requires_docker
async def test_pg_middleware_deny_continue(make_pg_session_with_decision):
    async with make_pg_session_with_decision(ApprovalDecision.DENY_CONTINUE) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "echo"), {"text": "1"})
        assert POLICY_DENIED_CONTINUE_MSG in str(ei.value)


@pytest.mark.requires_docker
async def test_pg_middleware_reserved_backend_code_remap(
    make_pg_session, approval_policy_reader_allow_all, backend_server
):
    # Ensure middleware is installed (requires approval_policy server); policy allows all
    async with make_pg_session({"backend": backend_server, "approval_policy": approval_policy_reader_allow_all}) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "raise_reserved"), {})
        # Backend used reserved policy code/message; middleware remaps to explicit misuse error
        s = str(ei.value)
        assert "policy_backend_reserved_misuse" in s
        # Optional: inspect error payload for code (-32952) if exposed
        # Note: fastmcp wraps ToolError with text; structured error may not be available here.


@pytest.mark.requires_docker
@pytest.mark.xfail(reason="In-proc raises drop ErrorData; stamp not inspectable at middleware layer")
async def test_pg_middleware_backend_stamp_misuse(make_pg_session, approval_policy_reader_allow_all, backend_server):
    async with make_pg_session({"backend": backend_server, "approval_policy": approval_policy_reader_allow_all}) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "raise_with_gateway_stamp"), {})
        s = str(ei.value)
        assert POLICY_BACKEND_RESERVED_MISUSE_MSG in s


@pytest.mark.requires_docker
async def test_pg_middleware_backend_stamp_misuse_via_proxy(
    make_pg_session, approval_policy_reader_allow_all, backend_server
):
    # Backend raises an McpError with a spoofed gateway stamp

    # Wrap backend in a FastMCP proxy so downstream errors arrive as result-path
    # CallToolResult (structured ErrorData preserved)

    proxy = FastMCP.as_proxy(backend_server)

    async with make_pg_session({"proxy": proxy, "approval_policy": approval_policy_reader_allow_all}) as sess:
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("proxy", "raise_with_gateway_stamp"), {})
        s = str(ei.value)
        assert POLICY_BACKEND_RESERVED_MISUSE_MSG in s


@pytest.mark.requires_docker
async def test_pg_middleware_ask_then_allow(make_pg_session_with_decision, approval_hub):
    # Capture the call_id from the notifier and approve it
    call_ids: list[str] = []

    async def notifier(call_id: str, _tool_key: str, _args_json: str | None):
        call_ids.append(call_id)
        # Approve immediately after notifier returns to avoid reentrancy
        asyncio.get_running_loop().call_soon(approval_hub.resolve, call_id, ContinueDecision())

    async with make_pg_session_with_decision(ApprovalDecision.ASK, notifier=notifier) as sess:
        res = await sess.call_tool(build_mcp_function("backend", "echo"), {"text": "3"})
        assert not res.is_error
        assert call_ids, "pending notifier should have been called"
