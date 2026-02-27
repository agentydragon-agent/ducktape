"""Tests for approval_gate ActionStorage."""

from __future__ import annotations

import pytest_bazel
from mcp.types import CallToolResult, TextContent

from approval_gate.models import ActionStatus, DoneState, PendingState, RejectedState, ToolCall
from approval_gate.storage import ActionStorage


async def test_create_and_get(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={"argv": ["echo", "hi"]})
    action = await storage.create(action_id="test-1", call=call, justification="testing", session_key=None)
    assert action.id == "test-1"
    assert isinstance(action.state, PendingState)

    fetched = await storage.get("test-1")
    assert fetched is not None
    assert fetched.id == "test-1"
    assert fetched.call.tool_name == "exec"
    assert fetched.justification == "testing"
    assert fetched.session_key is None


async def test_get_missing_returns_none(storage: ActionStorage):
    result = await storage.get("nonexistent-id")
    assert result is None


async def test_update_state(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={})
    await storage.create(action_id="test-2", call=call, justification="test", session_key="sk-1")
    updated = await storage.update_state(
        "test-2", DoneState(outcome=CallToolResult(content=[TextContent(type="text", text="ok")]))
    )
    assert updated is not None
    assert isinstance(updated.state, DoneState)
    assert isinstance(updated.state.outcome, CallToolResult)


async def test_list_pending(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={})
    await storage.create(action_id="p1", call=call, justification="a", session_key=None)
    await storage.create(action_id="p2", call=call, justification="b", session_key=None)
    await storage.update_state("p2", RejectedState(reason="no"))

    pending = await storage.list_by_status(ActionStatus.pending)
    ids = {a.id for a in pending}
    assert "p1" in ids
    assert "p2" not in ids


async def test_list_by_status_filter(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={})
    await storage.create(action_id="r1", call=call, justification="a", session_key=None)
    await storage.update_state("r1", RejectedState(reason="nope"))

    rejected = await storage.list_by_status(ActionStatus.rejected)
    assert any(a.id == "r1" for a in rejected)

    pending = await storage.list_by_status(ActionStatus.pending)
    assert not any(a.id == "r1" for a in pending)


async def test_list_all(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={})
    await storage.create(action_id="all-1", call=call, justification="x", session_key=None)
    await storage.create(action_id="all-2", call=call, justification="y", session_key=None)

    all_actions = await storage.list_by_status(None)
    ids = {a.id for a in all_actions}
    assert "all-1" in ids
    assert "all-2" in ids


async def test_session_key_stored(storage: ActionStorage):
    call = ToolCall(tool_name="exec", arguments={})
    await storage.create(action_id="sk-test", call=call, justification="need session", session_key="my-session-key")
    fetched = await storage.get("sk-test")
    assert fetched is not None
    assert fetched.session_key == "my-session-key"


if __name__ == "__main__":
    pytest_bazel.main()
