from __future__ import annotations

from typing import Callable
import uuid

from fastmcp.server import FastMCP
import pytest

from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp._shared.constants import POLICY_EVALUATOR_ERROR_MSG


def _docker_available() -> bool:
    try:
        import docker  # type: ignore

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


BAD_POLICY_SRC: str


## Removed: template-based seatbelt tests. Seatbelt now accepts only explicit policy.


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_container_timeout_causes_deny_abort(
    monkeypatch: pytest.MonkeyPatch,
    policy_fetch: Callable[[str], str],
    make_pg_compositor,
    make_policy_engine,
):
    # Force short timeout to trigger evaluator timeout
    monkeypatch.setenv("ADGN_POLICY_EVAL_TIMEOUT_SECS", "0.1")
    agent_id = f"t-{uuid.uuid4().hex[:8]}"
    # Policy that sleeps (exceeds timeout)
    SLEEPY = policy_fetch("sleepy_timeout")
    engine = make_policy_engine(SLEEPY, agent_id=agent_id)

    # Backend with one trivial tool
    backend = FastMCP("backend")

    @backend.tool("noop")
    def noop() -> str:
        return "ok"

    # Reader server
    reader = ApprovalPolicyServer(engine)

    async with make_pg_compositor({"backend": backend, "approval_policy": reader}) as (sess, _):
        # High-level client surfaces ToolError with message only; assert the canonical message
        with pytest.raises(Exception) as ei:
            await sess.call_tool(build_mcp_function("backend", "noop"), {})
        assert POLICY_EVALUATOR_ERROR_MSG in str(ei.value)
