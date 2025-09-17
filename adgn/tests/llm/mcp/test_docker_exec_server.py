from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import os

import anyio
from mcp import ClientSession
import pytest

from adgn.llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec


@asynccontextmanager
async def open_inproc_session() -> ClientSession:
    """Open an in-proc FastMCP docker_exec session.

    This keeps enter/exit in the same task (inside anyio.run in each test),
    avoiding anyio cancel-scope teardown issues from cross-task fixtures.
    """
    server = make_container_exec_mcp(image="alpine:3.20", describe=False)
    spec = make_inproc_slot_spec(server)
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        yield slot.session


def _extract_payload(resp):
    if getattr(resp, "structuredContent", None):
        return resp.structuredContent
    if hasattr(resp, "result") and isinstance(resp.result, dict):
        return resp.result
    raise AssertionError(f"Unexpected tool response shape: {resp!r}")


async def _call_exec(
    session: ClientSession,
    cmd: list[str],
    timeout_secs: float | None = None,
):
    payload: dict[str, object] = {"cmd": cmd}
    if timeout_secs is not None:
        payload["timeout_secs"] = timeout_secs
    response = await session.call_tool(name="docker_exec", arguments=payload)
    return _extract_payload(response)


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_hello_world() -> None:
    async def inner() -> None:
        async with open_inproc_session() as session:
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "docker_exec" in names

            payload = await _call_exec(session, ["/bin/echo", "hello"], timeout_secs=10)
            assert payload["exit_code"] == 0
            assert payload["timed_out"] is False
            assert "hello" in (payload["stdout"] or "")

    anyio.run(inner)


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_stderr_and_exit_code() -> None:
    async def inner() -> None:
        async with open_inproc_session() as session:
            payload = await _call_exec(
                session,
                ["sh", "-lc", "echo err 1>&2; exit 3"],
                timeout_secs=10,
            )
            expected_err_exit = 3  # magic number conveys exit code under test
            assert payload["exit_code"] == expected_err_exit
            assert "err" in (payload["stderr"] or "")

    anyio.run(inner)


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Requires local Docker engine",
)
def test_timeout_flag() -> None:
    async def inner() -> None:
        async with open_inproc_session() as session:
            payload = await _call_exec(
                session,
                ["sh", "-lc", "sleep 5"],
                timeout_secs=0.5,
            )
            assert payload["timed_out"] is True
            assert payload.get("exit_code") in (None, 124, 143, 137, 1, 255)

    anyio.run(inner)
