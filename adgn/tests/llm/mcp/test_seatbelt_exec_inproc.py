from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import os
from pathlib import Path

import anyio
from mcp.server.fastmcp.exceptions import ToolError
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.seatbelt_exec.server import make_seatbelt_exec_mcp
from adgn.seatbelt.model import (
    SBPLPolicy,
    ProcessRule,
    FileRule,
    PathFilter,
    MachLookupRule,
    SystemRule,
    TraceConfig,
)


@asynccontextmanager
async def open_inproc_session():
    """Open an in-proc FastMCP seatbelt_exec session, yielding (server, session).

    Keeps enter/exit in the same task (inside anyio.run in each test).
    """
    server = make_seatbelt_exec_mcp()
    spec = make_inproc_slot_spec(server)
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        yield server, slot.session


def make_default_restrictive_policy(trace: bool = False) -> SBPLPolicy:
    return SBPLPolicy(
        default_behavior="deny",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
        network=[],
        mach=MachLookupRule(global_names=[]),
        system=SystemRule(system_socket=False, sysctl_read=False),
        trace=TraceConfig(enabled=trace, path=None),
    )


def _extract_payload(resp):
    # Prefer structuredContent (Pydantic model return) else unwrap result
    sc = getattr(resp, "structuredContent", None)
    if sc is not None:
        return sc
    r = getattr(resp, "result", None)
    if r is not None:
        if isinstance(r, dict) and set(r.keys()) == {"result"}:
            return r["result"]
        return r
    if isinstance(resp, dict) and set(resp.keys()) == {"result"}:
        return resp["result"]
    return resp


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_sandbox_exec_echo_roundtrip() -> None:
    async def inner() -> None:
        async with open_inproc_session() as (_server, session):
            # Tools available
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "list_policies",
                "set_policy",
                "get_policy",
                "delete_policy",
                "sandbox_exec",
            }.issubset(names)

            # Write restrictive echo policy (allow exec + read subpath /)
            policy_id = "restrictive"
            # Build policy with Pydantic model to match server's expected schema
            policy_payload = make_default_restrictive_policy(trace=False).model_dump()
            resp = await session.call_tool(
                name="set_policy",
                arguments={"policy_id": policy_id, "policy": policy_payload},
            )
            assert _extract_payload(resp) == {}  # empty object

            # Execute echo under sandbox
            exec_resp = await session.call_tool(
                name="sandbox_exec",
                arguments={
                    "policy_id": policy_id,
                    "argv": ["/bin/echo", "HELLO_MINIMAL"],
                    "timeout_secs": 10,
                    "trace": False,
                },
            )
            payload = _extract_payload(exec_resp)
            assert payload["timeout"] is False
            assert payload["exit_code"] == 0
            assert payload["stdout_text"] == "HELLO_MINIMAL\n"
            # stderr should be empty or None
            assert payload.get("stderr_text") in ("", None)
            # duration exists and is a non-negative int
            assert (
                isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0
            )

    anyio.run(inner)


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_sandbox_exec_write_denied() -> None:
    """Attempt a file write that should be denied by the sandbox policy."""
    import secrets

    async def inner() -> None:
        async with open_inproc_session() as (_server, session):
            # Install a restrictive policy: allow exec + read, deny writes by default
            policy_id = "restrictive"

            await session.call_tool(
                name="set_policy",
                arguments={
                    "policy_id": policy_id,
                    "policy": make_default_restrictive_policy(trace=True).model_dump(),
                },
            )

            # Attempt to write to /tmp (normally allowed for a user; should be denied by sandbox)
            token = secrets.token_hex(6)
            out_path = f"/tmp/seatbelt_denied_{token}.txt"
            exec_resp = await session.call_tool(
                name="sandbox_exec",
                arguments={
                    "policy_id": policy_id,
                    "argv": ["/bin/sh", "-lc", f"echo DENIED > {out_path}"],
                    "timeout_secs": 5,
                    "trace": True,
                },
            )
            payload = _extract_payload(exec_resp)
            assert payload["timeout"] is False
            # Expect non-zero exit due to sandbox denial
            assert isinstance(payload["exit_code"], int) and payload["exit_code"] != 0
            # Stderr should have some diagnostic
            assert (payload.get("stderr_text") or "").strip() != ""
            # File should not exist (write was denied)
            assert not os.path.exists(out_path)
            # Trace collection remains flaky across versions; rely on stderr for now
            # TODO(mpokorny): Revisit trace enablement and policy for reliable capture

    anyio.run(inner)


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_sandbox_exec_timeout() -> None:
    """Command exceeding timeout should return timeout=True and no exit_code."""

    async def inner() -> None:
        async with open_inproc_session() as (_server, session):
            policy_id = "restrictive"
            policy = make_default_restrictive_policy()
            await session.call_tool(
                name="set_policy",
                arguments={"policy_id": policy_id, "policy": policy.model_dump()},
            )
            exec_resp = await session.call_tool(
                name="sandbox_exec",
                arguments={
                    "policy_id": policy_id,
                    "argv": ["/bin/sh", "-lc", "sleep 2"],
                    "timeout_secs": 0.5,
                    "trace": False,
                },
            )
            payload = _extract_payload(exec_resp)
            assert payload["timeout"] is True
            assert payload["exit_code"] is None
            assert (
                isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0
            )

    anyio.run(inner)


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_sandbox_exec_cwd_and_env(tmp_path: Path) -> None:
    """Verify cwd and env injection."""

    async def inner() -> None:
        async with open_inproc_session() as (_server, session):
            policy_id = "restrictive"
            policy = make_default_restrictive_policy()
            await session.call_tool(
                name="set_policy",
                arguments={"policy_id": policy_id, "policy": policy.model_dump()},
            )
            exec_resp = await session.call_tool(
                name="sandbox_exec",
                arguments={
                    "policy_id": policy_id,
                    "argv": ["/bin/sh", "-lc", "pwd; echo $FOO"],
                    "cwd": str(tmp_path),
                    "env": {"FOO": "BAR"},
                    "timeout_secs": 5,
                    "trace": False,
                },
            )
            payload = _extract_payload(exec_resp)
            assert payload["timeout"] is False
            assert payload["exit_code"] == 0
            assert payload["stdout_text"].splitlines()[:2] == [str(tmp_path), "BAR"]

    anyio.run(inner)


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_policy_crud() -> None:
    async def inner() -> None:
        async with open_inproc_session() as (_server, session):
            # list should start empty
            lp = await session.call_tool(name="list_policies", arguments={})
            assert lp.structuredContent["result"] == []

            # set one policy
            pid = "p1"
            policy = make_default_restrictive_policy()
            await session.call_tool(
                name="set_policy",
                arguments={"policy_id": pid, "policy": policy.model_dump()},
            )

            # list includes it
            lp2 = await session.call_tool(name="list_policies", arguments={})
            assert lp2.structuredContent["result"] == [pid]

            # get returns the policy
            gp = await session.call_tool(
                name="get_policy", arguments={"policy_id": pid}
            )
            assert _extract_payload(gp) == policy.model_dump()

            # delete and get should fail
            await session.call_tool(name="delete_policy", arguments={"policy_id": pid})
            with pytest.raises(ToolError):
                # Use server.call_tool to assert tool error raising behavior
                await _server.call_tool("get_policy", {"policy_id": pid})

    anyio.run(inner)
