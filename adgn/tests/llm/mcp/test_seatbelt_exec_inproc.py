from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import os

import anyio
from mcp import ClientSession
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.seatbelt_exec.server import make_seatbelt_exec_mcp


@asynccontextmanager
async def open_inproc_session() -> ClientSession:
    """Open an in-proc FastMCP seatbelt_exec session.

    Keeps enter/exit in the same task (inside anyio.run in each test).
    """
    server = make_seatbelt_exec_mcp()
    spec = make_inproc_slot_spec(server)
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        yield slot.session


def _extract_payload(resp):
    # Prefer structuredContent (Pydantic model return) else dict result
    if getattr(resp, "structuredContent", None) is not None:
        return resp.structuredContent
    if hasattr(resp, "result"):
        return resp.result
    raise AssertionError(f"Unexpected tool response shape: {resp!r}")


@pytest.mark.requires_sandbox_exec
@pytest.mark.shell
def test_sandbox_exec_echo_roundtrip() -> None:
    async def inner() -> None:
        async with open_inproc_session() as session:
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
            from adgn.seatbelt.model import (
                SBPLPolicy,
                ProcessRule,
                FileRule,
                PathFilter,
                MachLookupRule,
                SystemRule,
                TraceConfig,
            )

            policy_model = SBPLPolicy(
                default_behavior="deny",
                process=ProcessRule(allow_process_star=True, allow_signal_self=True),
                files=[
                    FileRule(op="file-map-executable", filters=[]),
                    FileRule(
                        op="file-read*", filters=[PathFilter(kind="subpath", value="/")]
                    ),
                ],
                network=[],
                mach=MachLookupRule(global_names=[]),
                system=SystemRule(system_socket=False, sysctl_read=False),
                trace=TraceConfig(enabled=False, path=None),
            )
            policy_payload = policy_model.model_dump()
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
        async with open_inproc_session() as session:
            # Install a restrictive policy: allow exec + read, deny writes by default
            policy_id = "restrictive"
            from adgn.seatbelt.model import (
                SBPLPolicy,
                ProcessRule,
                FileRule,
                PathFilter,
                MachLookupRule,
                SystemRule,
                TraceConfig,
            )

            policy_model = SBPLPolicy(
                default_behavior="deny",
                process=ProcessRule(allow_process_star=True, allow_signal_self=True),
                files=[
                    FileRule(op="file-map-executable", filters=[]),
                    FileRule(
                        op="file-read*", filters=[PathFilter(kind="subpath", value="/")]
                    ),
                ],
                network=[],
                mach=MachLookupRule(global_names=[]),
                system=SystemRule(system_socket=False, sysctl_read=False),
                trace=TraceConfig(enabled=True, path=None),
            )
            await session.call_tool(
                name="set_policy",
                arguments={"policy_id": policy_id, "policy": policy_model.model_dump()},
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
            # TODO: when server includes unified_sandbox_denies, assert on a deny snippet

    anyio.run(inner)
