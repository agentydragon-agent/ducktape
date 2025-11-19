"""Tests for agents MCP server conversion functions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adgn.agent.mcp_bridge.servers.agents import (
    DecisionType,
    _convert_tool_call_record_to_history,
)
from adgn.agent.persist import ApprovalOutcome, Decision, ToolCall, ToolCallExecution, ToolCallRecord
from mcp import types as mcp_types


def make_tool_call_record(
    *,
    call_id: str = "call-123",
    run_id: str = "run-456",
    agent_id: str = "agent-789",
    tool_name: str = "test_tool",
    args_json: str | None = '{"arg1": "value1"}',
    decision: Decision | None = None,
    execution: ToolCallExecution | None = None,
) -> ToolCallRecord:
    """Factory function to create ToolCallRecord with sensible defaults."""
    return ToolCallRecord(
        call_id=call_id,
        run_id=run_id,
        agent_id=agent_id,
        tool_call=ToolCall(name=tool_name, call_id=call_id, args_json=args_json),
        decision=decision,
        execution=execution,
    )


def test_convert_tool_call_record_pending():
    """PENDING tool calls (no decision) should return None."""
    record = make_tool_call_record()

    result = _convert_tool_call_record_to_history(record)
    assert result is None


def test_convert_tool_call_record_executing():
    """EXECUTING tool calls (decision but no execution) should be converted."""
    decision = Decision(
        outcome=ApprovalOutcome.USER_APPROVE,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    record = make_tool_call_record(decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.call_id == "call-123"
    assert result.tool == "test_tool"
    assert result.args == {"arg1": "value1"}
    assert result.decision == DecisionType.APPROVED
    assert result.reason is None
    assert result.timestamp == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert result.decided_by == "human"


def test_convert_tool_call_record_completed():
    """COMPLETED tool calls (decision and execution) should be converted."""
    decision = Decision(
        outcome=ApprovalOutcome.POLICY_ALLOW,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    execution = ToolCallExecution(
        completed_at=datetime(2025, 1, 15, 10, 30, 5, tzinfo=timezone.utc),
        output=mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="Success!")], isError=False),
    )

    record = make_tool_call_record(decision=decision, execution=execution)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.call_id == "call-123"
    assert result.tool == "test_tool"
    assert result.args == {"arg1": "value1"}
    assert result.decision == DecisionType.APPROVED
    assert result.reason is None
    assert result.timestamp == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert result.decided_by == "policy"


def test_convert_tool_call_record_rejected():
    """Rejected tool calls should have REJECTED decision and reason."""
    decision = Decision(
        outcome=ApprovalOutcome.USER_DENY_ABORT,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason="User rejected this action",
    )

    record = make_tool_call_record(decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.decision == DecisionType.REJECTED
    assert result.reason == "User rejected this action"
    assert result.decided_by == "human"


def test_convert_tool_call_record_policy_deny():
    """Policy denials should be marked as decided by policy."""
    decision = Decision(
        outcome=ApprovalOutcome.POLICY_DENY_CONTINUE,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    record = make_tool_call_record(decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.decision == DecisionType.REJECTED
    assert result.reason == "Denied by policy_deny_continue"
    assert result.decided_by == "policy"


def test_convert_tool_call_record_no_reason_rejection():
    """Rejections without explicit reason should get a default reason."""
    decision = Decision(
        outcome=ApprovalOutcome.POLICY_DENY_ABORT,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    record = make_tool_call_record(args_json='{}', decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.decision == DecisionType.REJECTED
    assert result.reason == "Denied by policy_deny_abort"


def test_convert_tool_call_record_invalid_json():
    """Invalid JSON in args_json should be handled gracefully."""
    decision = Decision(
        outcome=ApprovalOutcome.USER_APPROVE,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    record = make_tool_call_record(args_json="invalid json{", decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.args == {}  # Should default to empty dict


def test_convert_tool_call_record_null_args():
    """Null args_json should result in empty args dict."""
    decision = Decision(
        outcome=ApprovalOutcome.USER_APPROVE,
        decided_at=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        reason=None,
    )

    record = make_tool_call_record(args_json=None, decision=decision)

    result = _convert_tool_call_record_to_history(record)
    assert result is not None
    assert result.args == {}
