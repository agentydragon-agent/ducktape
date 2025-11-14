from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastmcp.client import Client
import pytest

from adgn.mcp.exec.seatbelt import (
    SandboxExecArgs,
    SeatbeltExecMCP,
)
from adgn.mcp.testing.typed_stubs import TypedClient
from adgn.seatbelt.model import (
    DefaultBehavior,
    FileOp,
    FileRule,
    MachLookupRule,
    ProcessRule,
    SBPLPolicy,
    Subpath,
    SystemRule,
    TraceConfig,
)
from tests._markers import REQUIRES_SANDBOX_EXEC

pytestmark = [*REQUIRES_SANDBOX_EXEC, pytest.mark.shell]


@pytest.fixture
def open_seatbelt_session(sqlite_persistence):
    @asynccontextmanager
    async def _open():
        import docker

        server = SeatbeltExecMCP(
            name="seatbelt_exec",
            agent_id="test-agent",
            persistence=sqlite_persistence,
            docker_client=docker.from_env(),
        )
        async with Client(server) as sess:
            yield server, sess

    return _open


def make_default_restrictive_policy(trace: bool = False) -> SBPLPolicy:
    return SBPLPolicy(
        default_behavior=DefaultBehavior.DENY,
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op=FileOp.FILE_MAP_EXECUTABLE, filters=[]),
            FileRule(op=FileOp.FILE_READ_STAR, filters=[Subpath(subpath="/")]),
        ],
        network=[],
        mach=MachLookupRule(global_names=[]),
        system=SystemRule(system_socket=False, sysctl_read=False),
        trace=TraceConfig(enabled=trace, path=None),
    )


def _extract_payload(resp):
    # Prefer structured_content (FastMCP dataclass) else unwrap result
    sc = getattr(resp, "structured_content", None)
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


@pytest.mark.asyncio
async def test_sandbox_exec_echo_roundtrip(open_seatbelt_session) -> None:
    async with open_seatbelt_session() as (_server, session):
        # Execute echo under sandbox (typed client)
        client = TypedClient.from_server(_server, session)
        res = await client.sandbox_exec(
            SandboxExecArgs(
                policy=make_default_restrictive_policy(trace=False),
                argv=["/bin/echo", "HELLO_MINIMAL"],
                max_bytes=100000,
                timeout_ms=10_000,
                trace=False,
            )
        )
        assert res.timeout is False
        assert res.exit_code == 0
        assert isinstance(res.stdout, str)  # Short output should not be truncated
        assert res.stdout == "HELLO_MINIMAL\n"
        # stderr should be empty or None
        assert isinstance(res.stderr, str)  # Short error should not be truncated
        assert res.stderr in ("", None)
        # duration exists and is a non-negative int
        assert isinstance(res.duration_ms, int) and res.duration_ms >= 0


@pytest.mark.asyncio
async def test_sandbox_exec_write_denied(open_seatbelt_session) -> None:
    """Attempt a file write that should be denied by the sandbox policy."""
    import secrets

    async with open_seatbelt_session() as (_server, session):
        # Attempt to write to /tmp (normally allowed for a user; should be denied by sandbox)
        token = secrets.token_hex(6)
        out_path = f"/tmp/seatbelt_denied_{token}.txt"
        client = TypedClient.from_server(_server, session)
        res = await client.sandbox_exec(
            SandboxExecArgs(
                policy=make_default_restrictive_policy(trace=True),
                argv=["/bin/sh", "-lc", f"echo DENIED > {out_path}"],
                max_bytes=100000,
                timeout_ms=5_000,
                trace=True,
            )
        )
        assert res.timeout is False
        # Expect non-zero exit due to sandbox denial
        assert isinstance(res.exit_code, int) and res.exit_code != 0
        # Stderr should have some diagnostic
        assert isinstance(res.stderr, str)  # Short error should not be truncated
        assert res.stderr != ""
        # File should not exist (write was denied)
        assert not os.path.exists(out_path)
        # Trace collection remains flaky across versions; rely on stderr for now
        # TODO(mpokorny): Revisit trace enablement and policy for reliable capture


@pytest.mark.asyncio
async def test_sandbox_exec_timeout(open_seatbelt_session) -> None:
    """Command exceeding timeout should return timeout=True and no exit_code."""

    async with open_seatbelt_session() as (_server, session):
        policy = make_default_restrictive_policy()
        client = TypedClient.from_server(_server, session)
        res = await client.sandbox_exec(
            SandboxExecArgs(
                policy=policy,
                argv=["/bin/sh", "-lc", "sleep 2"],
                max_bytes=100000,
                timeout_ms=500,
                trace=False,
            )
        )
        assert res.timeout is True
        assert res.exit_code is None
        assert isinstance(res.duration_ms, int) and res.duration_ms >= 0


@pytest.mark.asyncio
async def test_sandbox_exec_cwd_and_env(tmp_path: Path, open_seatbelt_session) -> None:
    """Verify cwd and env injection (async)."""
    async with open_seatbelt_session() as (_server, session):
        policy = make_default_restrictive_policy()
        client = TypedClient.from_server(_server, session)
        res = await client.sandbox_exec(
            SandboxExecArgs(
                policy=policy,
                argv=["/bin/sh", "-lc", "pwd; echo $FOO"],
                cwd=str(tmp_path),
                env={"FOO": "BAR"},
                max_bytes=100000,
                timeout_ms=5_000,
                trace=False,
            )
        )
        assert res.timeout is False
        assert res.exit_code == 0
        assert isinstance(res.stdout, str)  # Short output should not be truncated
        assert res.stdout.splitlines()[:2] == [str(tmp_path), "BAR"]

    # No policy CRUD tests; server no longer stores policies.
