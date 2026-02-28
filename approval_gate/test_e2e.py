"""E2E tests for the approval gate — fully in-process, no HTTP servers.

Operator actions (approve/reject) are called via gate.decide() directly
because in-process clients use memory transport (not stdio), so FastMCP's
per-tool auth check enforces operator scope even without HTTP middleware.
The MCP auth boundary for operator tools is covered by test_operator_auth.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_bazel
from fastmcp import FastMCP
from fastmcp.client import Client
from mcp import types as mcp_types

from approval_gate.models import Action, ActionRef, ActionStatus, ApproveDecision, DenyDecision
from approval_gate.predicates import Approved, NeedsHumanDecision
from approval_gate.proxy_server import ApprovalGateServer

_INSTRUCTIONS_TEMPLATE = str(Path(__file__).parent / "instructions.mako")


@pytest.fixture
async def backend():
    calls: list[dict] = []
    srv = FastMCP("test-backend")

    @srv.tool()
    async def echo(text: str) -> str:
        calls.append({"text": text})
        return f"echoed: {text}"

    return srv, calls


def _make_gate(srv, tmp_path, predicate, db_name="gate.db"):
    return ApprovalGateServer(
        backend=srv,
        db_path=tmp_path / db_name,
        predicate=predicate,
        public_base_url="http://test",
        instructions_template_path=_INSTRUCTIONS_TEMPLATE,
    )


@pytest.fixture
async def gate(backend, tmp_path):
    srv, _ = backend
    return _make_gate(srv, tmp_path, lambda tool, args: NeedsHumanDecision())


async def _wait_for_status(client: Client, action_id: str, status: ActionStatus) -> Action:
    while True:
        contents = await client.read_resource(f"resource://actions/{action_id}")
        item = contents[0]
        assert isinstance(item, mcp_types.TextResourceContents)
        action = Action.model_validate_json(item.text)
        if action.state.status == status:
            return action
        await asyncio.sleep(0.05)


async def test_tool_list_wraps_backend_tools(gate):
    """MCP tool list exposes backend tools wrapped with the approval-gate schema envelope."""
    async with Client(gate) as client:
        tools = await client.list_tools()

    names = [t.name for t in tools]
    assert "echo" in names

    echo = next(t for t in tools if t.name == "echo")
    props = echo.inputSchema["properties"]
    assert "justification" in props
    assert "session_key" in props
    assert "input" in props
    assert "text" in props["input"]["properties"]


async def test_approve_executes_backend_tool(gate, backend):
    """Happy path: tool call queued → operator approves → backend runs → action done."""
    _, calls = backend
    async with Client(gate) as client:
        result = await client.call_tool_mcp("echo", {"input": {"text": "hello"}, "justification": "test"})
        action_id = ActionRef.model_validate_json(result.content[0].text).action_id
        await gate.decide(action_id, ApproveDecision())
        async with asyncio.timeout(5.0):
            await _wait_for_status(client, action_id, ActionStatus.done)
    assert calls == [{"text": "hello"}]


async def test_reject_leaves_action_rejected_and_skips_backend(gate, backend):
    """Reject path: tool call queued → operator rejects → rejected state, backend not called."""
    _, calls = backend
    async with Client(gate) as client:
        result = await client.call_tool_mcp("echo", {"input": {"text": "no-run"}, "justification": "test"})
        action_id = ActionRef.model_validate_json(result.content[0].text).action_id
        await gate.decide(action_id, DenyDecision(reason="test rejection"))
        async with asyncio.timeout(5.0):
            await _wait_for_status(client, action_id, ActionStatus.rejected)
    assert calls == []


async def test_auto_approve_predicate_skips_queue(backend, tmp_path):
    """Auto-approve predicate: tool call immediately executes without any operator action."""
    srv, calls = backend
    gate = _make_gate(srv, tmp_path, lambda tool, args: Approved(), db_name="gate_auto.db")
    async with Client(gate) as client:
        result = await client.call_tool_mcp("echo", {"input": {"text": "auto"}, "justification": "auto"})
        action_id = ActionRef.model_validate_json(result.content[0].text).action_id
        async with asyncio.timeout(5.0):
            await _wait_for_status(client, action_id, ActionStatus.done)
    assert calls == [{"text": "auto"}]


if __name__ == "__main__":
    pytest_bazel.main()
