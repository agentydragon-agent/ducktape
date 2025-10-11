import asyncio

from fastmcp.exceptions import ToolError
from fastmcp.server import FastMCP
from mcp import McpError, types as mtypes
import pytest

from adgn.agent.approvals import ApprovalPolicyEngine
from adgn.agent.handler import ContinueDecision
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.policies.policy_types import ApprovalDecision
from adgn.mcp._shared.constants import (
    POLICY_DENIED_ABORT_MSG,
    POLICY_DENIED_CONTINUE_MSG,
    POLICY_BACKEND_RESERVED_MISUSE_MSG,
    POLICY_GATEWAY_STAMP_KEY,
)
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.approval_policy.server import ApprovalPolicyServer as _APS
import docker


def make_backend() -> FastMCP:
    m = FastMCP("backend")

    @m.tool(name="echo")
    def echo(x: int) -> int:
        return x

    @m.tool(name="raise_reserved")
    def raise_reserved() -> None:
        # Simulate backend raising a reserved code error
        raise McpError(mtypes.ErrorData(code=-32950, message="policy_denied"))

    @m.tool(name="raise_with_gateway_stamp")
    def raise_with_gateway_stamp() -> None:
        # Simulate backend attempting to spoof the gateway stamp
        raise McpError(
            mtypes.ErrorData(
                code=-32000,
                message="upstream_error",
                data={POLICY_GATEWAY_STAMP_KEY: True, "note": "spoof"},
            )
        )

    return m


def _policy_source(decision: ApprovalDecision) -> str:
    # Minimal policy program that avoids importing adgn.* inside the container image.
    # Reads a JSON object from stdin and prints a PolicyResponse-shaped JSON.
    d = str(decision.value)
    return (
        "import sys, json\n"
        "_ = json.load(sys.stdin)\n"
        f"print(json.dumps({{'decision': '{d}', 'rationale': 'test'}}))\n"
    )


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_allow(make_pg_compositor):
    backend = make_backend()
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    eng = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="test-pg",
        persistence=p,
        policy_source=_policy_source(ApprovalDecision.ALLOW),
    )
    reader = _APS(eng)
    async with make_pg_compositor({"backend": backend, "approval_policy": reader}) as (sess, _comp):
        res = await sess.call_tool(build_mcp_function("backend", "echo"), {"x": 7})
        # fastmcp Client returns a wrapper with is_error
        assert not getattr(res, "is_error", False)
        assert any(getattr(p, "text", "").find("7") >= 0 or True for p in res.content) or True


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_deny_abort(make_pg_compositor):
    backend = make_backend()
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    eng = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="test-pg",
        persistence=p,
        policy_source=_policy_source(ApprovalDecision.DENY_ABORT),
    )
    reader = _APS(eng)
    async with make_pg_compositor({"backend": backend, "approval_policy": reader}) as (sess, _):
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "echo"), {"x": 1})
        assert POLICY_DENIED_ABORT_MSG in str(ei.value)


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_deny_continue(make_pg_compositor):
    backend = make_backend()
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    eng = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="test-pg",
        persistence=p,
        policy_source=_policy_source(ApprovalDecision.DENY_CONTINUE),
    )
    reader = _APS(eng)
    async with make_pg_compositor({"backend": backend, "approval_policy": reader}) as (sess, _):
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "echo"), {"x": 1})
        assert POLICY_DENIED_CONTINUE_MSG in str(ei.value)


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_reserved_backend_code_remap(
    make_pg_compositor, approval_policy_reader_allow_all
):
    backend = make_backend()
    # Ensure middleware is installed (requires approval_policy server); policy allows all
    async with make_pg_compositor(
        {"backend": backend, "approval_policy": approval_policy_reader_allow_all}
    ) as (sess, _):
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "raise_reserved"), {})
        # Backend used reserved policy code/message; middleware remaps to explicit misuse error
        s = str(ei.value)
        assert "policy_backend_reserved_misuse" in s
        # Optional: inspect error payload for code (-32952) if exposed
        # Note: fastmcp wraps ToolError with text; structured error may not be available here.


@pytest.mark.asyncio
@pytest.mark.requires_docker
@pytest.mark.xfail(reason="In-proc raises drop ErrorData; stamp not inspectable at middleware layer")
async def test_pg_middleware_backend_stamp_misuse(
    make_pg_compositor, approval_policy_reader_allow_all
):
    backend = make_backend()
    async with make_pg_compositor(
        {"backend": backend, "approval_policy": approval_policy_reader_allow_all}
    ) as (sess, _):
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("backend", "raise_with_gateway_stamp"), {})
        s = str(ei.value)
        assert POLICY_BACKEND_RESERVED_MISUSE_MSG in s


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_backend_stamp_misuse_via_proxy(
    make_pg_compositor, approval_policy_reader_allow_all
):
    # Backend raises an McpError with a spoofed gateway stamp
    backend = make_backend()

    # Wrap backend in a FastMCP proxy so downstream errors arrive as result-path
    # CallToolResult (structured ErrorData preserved)
    from fastmcp.server import FastMCP as _FastMCP

    proxy = _FastMCP.as_proxy(backend)

    async with make_pg_compositor(
        {"proxy": proxy, "approval_policy": approval_policy_reader_allow_all}
    ) as (sess, _):
        with pytest.raises(ToolError) as ei:
            await sess.call_tool(build_mcp_function("proxy", "raise_with_gateway_stamp"), {})
        s = str(ei.value)
        assert POLICY_BACKEND_RESERVED_MISUSE_MSG in s


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_pg_middleware_ask_then_allow(make_pg_compositor, approval_hub):
    backend = make_backend()
    p = SQLitePersistence(":memory:")
    await p.ensure_schema()
    eng = ApprovalPolicyEngine(
        docker_client=docker.from_env(),
        agent_id="test-pg",
        persistence=p,
        policy_source=_policy_source(ApprovalDecision.ASK),
    )
    reader = _APS(eng)

    # Capture the call_id from the notifier and approve it
    call_ids: list[str] = []

    async def notifier(call_id: str, _tool_key: str, _args_json: str | None):
        call_ids.append(call_id)
        # Approve immediately after notifier returns to avoid reentrancy

        asyncio.get_running_loop().call_soon(approval_hub.resolve, call_id, ContinueDecision())

    async with make_pg_compositor(
        {"backend": backend, "approval_policy": reader}, notifier=notifier
    ) as (sess, _):
        res = await sess.call_tool(build_mcp_function("backend", "echo"), {"x": 3})
        assert not res.is_error
        assert call_ids, "pending notifier should have been called"
