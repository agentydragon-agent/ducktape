from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from mcp import types as mcp_types

from adgn.agent.persist import ApprovalOutcome, Decision, ToolCall, ToolCallExecution, ToolCallRecord
from adgn.agent.persist.sqlite import SQLitePersistence


@pytest.fixture
async def persistence(tmp_path: Path) -> SQLitePersistence:
    """Create a fresh SQLite persistence instance with schema."""
    db_path = tmp_path / "test.db"
    persist = SQLitePersistence(db_path)
    await persist.ensure_schema()
    return persist


@pytest.mark.asyncio
async def test_schema_creation_drops_old_tables(tmp_path: Path) -> None:
    """Test that ensure_schema drops old tables and creates new tool_calls table."""
    db_path = tmp_path / "test.db"
    persist = SQLitePersistence(db_path)

    # Create schema
    await persist.ensure_schema()

    # Verify tool_calls table exists and old approvals table doesn't
    async with persist._db_connection() as db:
        # Check that tool_calls table exists
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tool_calls'")
        result = await cur.fetchone()
        assert result is not None, "tool_calls table should exist"

        # Check that old approvals table doesn't exist
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='approvals'")
        result = await cur.fetchone()
        assert result is None, "approvals table should not exist"

        # Check that schema_version table doesn't exist
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        result = await cur.fetchone()
        assert result is None, "schema_version table should not exist"


@pytest.mark.asyncio
async def test_save_and_get_tool_call_pending(persistence: SQLitePersistence) -> None:
    """Test saving and retrieving a PENDING tool call (no decision, no execution)."""
    # Create a PENDING tool call record
    record = ToolCallRecord(
        call_id="test-call-1",
        run_id="test-run-1",
        agent_id="test-agent-1",
        tool_call=ToolCall(name="test_tool", call_id="test-call-1", args_json='{"arg": "value"}'),
        decision=None,
        execution=None,
    )

    # Save it
    await persistence.save_tool_call(record)

    # Retrieve it
    retrieved = await persistence.get_tool_call("test-call-1")

    # Verify
    assert retrieved is not None
    assert retrieved.call_id == "test-call-1"
    assert retrieved.run_id == "test-run-1"
    assert retrieved.agent_id == "test-agent-1"
    assert retrieved.tool_call.name == "test_tool"
    assert retrieved.tool_call.args_json == '{"arg": "value"}'
    assert retrieved.decision is None
    assert retrieved.execution is None


@pytest.mark.asyncio
async def test_save_and_get_tool_call_executing(persistence: SQLitePersistence) -> None:
    """Test saving and retrieving an EXECUTING tool call (decision but no execution)."""
    # Create an EXECUTING tool call record
    decision = Decision(
        outcome=ApprovalOutcome.USER_APPROVE,
        decided_at=datetime.now(UTC),
        reason=None,
    )
    record = ToolCallRecord(
        call_id="test-call-2",
        run_id="test-run-2",
        agent_id="test-agent-2",
        tool_call=ToolCall(name="another_tool", call_id="test-call-2", args_json='{"foo": "bar"}'),
        decision=decision,
        execution=None,
    )

    # Save it
    await persistence.save_tool_call(record)

    # Retrieve it
    retrieved = await persistence.get_tool_call("test-call-2")

    # Verify
    assert retrieved is not None
    assert retrieved.call_id == "test-call-2"
    assert retrieved.tool_call.name == "another_tool"
    assert retrieved.decision is not None
    assert retrieved.decision.outcome == ApprovalOutcome.USER_APPROVE
    assert retrieved.decision.reason is None
    assert retrieved.execution is None


@pytest.mark.asyncio
async def test_save_and_get_tool_call_completed(persistence: SQLitePersistence) -> None:
    """Test saving and retrieving a COMPLETED tool call (decision and execution)."""
    # Create a COMPLETED tool call record
    decision = Decision(
        outcome=ApprovalOutcome.POLICY_ALLOW,
        decided_at=datetime.now(UTC),
        reason=None,
    )
    execution = ToolCallExecution(
        completed_at=datetime.now(UTC),
        output=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Success!")], isError=False
        ),
    )
    record = ToolCallRecord(
        call_id="test-call-3",
        run_id="test-run-3",
        agent_id="test-agent-3",
        tool_call=ToolCall(name="exec", call_id="test-call-3", args_json='{"cmd": "ls"}'),
        decision=decision,
        execution=execution,
    )

    # Save it
    await persistence.save_tool_call(record)

    # Retrieve it
    retrieved = await persistence.get_tool_call("test-call-3")

    # Verify
    assert retrieved is not None
    assert retrieved.call_id == "test-call-3"
    assert retrieved.tool_call.name == "exec"
    assert retrieved.decision is not None
    assert retrieved.decision.outcome == ApprovalOutcome.POLICY_ALLOW
    assert retrieved.execution is not None
    assert retrieved.execution.output.isError is False
    assert len(retrieved.execution.output.content) == 1
    assert isinstance(retrieved.execution.output.content[0], mcp_types.TextContent)
    assert retrieved.execution.output.content[0].text == "Success!"


@pytest.mark.asyncio
async def test_list_tool_calls_all(persistence: SQLitePersistence) -> None:
    """Test listing all tool calls."""
    # Create multiple records
    records = [
        ToolCallRecord(
            call_id=f"call-{i}",
            run_id=f"run-{i % 2}",  # Alternate between two runs
            agent_id="test-agent",
            tool_call=ToolCall(name=f"tool_{i}", call_id=f"call-{i}", args_json='{}'),
            decision=None,
            execution=None,
        )
        for i in range(5)
    ]

    # Save all
    for record in records:
        await persistence.save_tool_call(record)

    # List all
    all_calls = await persistence.list_tool_calls()

    # Verify
    assert len(all_calls) == 5
    assert {r.call_id for r in all_calls} == {f"call-{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_list_tool_calls_by_run_id(persistence: SQLitePersistence) -> None:
    """Test listing tool calls filtered by run_id."""
    # Create records for different runs
    run_1_records = [
        ToolCallRecord(
            call_id=f"run1-call-{i}",
            run_id="run-1",
            agent_id="test-agent",
            tool_call=ToolCall(name=f"tool_{i}", call_id=f"run1-call-{i}", args_json='{}'),
            decision=None,
            execution=None,
        )
        for i in range(3)
    ]
    run_2_records = [
        ToolCallRecord(
            call_id=f"run2-call-{i}",
            run_id="run-2",
            agent_id="test-agent",
            tool_call=ToolCall(name=f"tool_{i}", call_id=f"run2-call-{i}", args_json='{}'),
            decision=None,
            execution=None,
        )
        for i in range(2)
    ]

    # Save all
    for record in run_1_records + run_2_records:
        await persistence.save_tool_call(record)

    # List for run-1
    run_1_calls = await persistence.list_tool_calls(run_id="run-1")
    assert len(run_1_calls) == 3
    assert all(r.run_id == "run-1" for r in run_1_calls)

    # List for run-2
    run_2_calls = await persistence.list_tool_calls(run_id="run-2")
    assert len(run_2_calls) == 2
    assert all(r.run_id == "run-2" for r in run_2_calls)


@pytest.mark.asyncio
async def test_update_tool_call_from_pending_to_executing(persistence: SQLitePersistence) -> None:
    """Test updating a tool call from PENDING to EXECUTING state."""
    # Create PENDING record
    record = ToolCallRecord(
        call_id="test-call-update",
        run_id="test-run",
        agent_id="test-agent",
        tool_call=ToolCall(name="test_tool", call_id="test-call-update", args_json='{}'),
        decision=None,
        execution=None,
    )
    await persistence.save_tool_call(record)

    # Update to EXECUTING
    decision = Decision(
        outcome=ApprovalOutcome.USER_APPROVE,
        decided_at=datetime.now(UTC),
        reason=None,
    )
    updated_record = ToolCallRecord(
        call_id="test-call-update",
        run_id="test-run",
        agent_id="test-agent",
        tool_call=record.tool_call,
        decision=decision,
        execution=None,
    )
    await persistence.save_tool_call(updated_record)

    # Retrieve and verify
    retrieved = await persistence.get_tool_call("test-call-update")
    assert retrieved is not None
    assert retrieved.decision is not None
    assert retrieved.decision.outcome == ApprovalOutcome.USER_APPROVE
    assert retrieved.execution is None


@pytest.mark.asyncio
async def test_update_tool_call_from_executing_to_completed(persistence: SQLitePersistence) -> None:
    """Test updating a tool call from EXECUTING to COMPLETED state."""
    # Create EXECUTING record
    decision = Decision(
        outcome=ApprovalOutcome.POLICY_ALLOW,
        decided_at=datetime.now(UTC),
        reason=None,
    )
    record = ToolCallRecord(
        call_id="test-call-complete",
        run_id="test-run",
        agent_id="test-agent",
        tool_call=ToolCall(name="test_tool", call_id="test-call-complete", args_json='{}'),
        decision=decision,
        execution=None,
    )
    await persistence.save_tool_call(record)

    # Update to COMPLETED
    execution = ToolCallExecution(
        completed_at=datetime.now(UTC),
        output=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Done!")], isError=False
        ),
    )
    completed_record = ToolCallRecord(
        call_id="test-call-complete",
        run_id="test-run",
        agent_id="test-agent",
        tool_call=record.tool_call,
        decision=decision,
        execution=execution,
    )
    await persistence.save_tool_call(completed_record)

    # Retrieve and verify
    retrieved = await persistence.get_tool_call("test-call-complete")
    assert retrieved is not None
    assert retrieved.decision is not None
    assert retrieved.execution is not None
    assert retrieved.execution.output.content[0].text == "Done!"


@pytest.mark.asyncio
async def test_get_nonexistent_tool_call(persistence: SQLitePersistence) -> None:
    """Test that getting a non-existent tool call returns None."""
    result = await persistence.get_tool_call("nonexistent-call")
    assert result is None


@pytest.mark.asyncio
async def test_json_serialization_roundtrip(persistence: SQLitePersistence) -> None:
    """Test that JSON serialization/deserialization preserves all data."""
    # Create a complex record with all fields populated
    decision = Decision(
        outcome=ApprovalOutcome.USER_DENY_ABORT,
        decided_at=datetime.now(UTC),
        reason="Security risk detected",
    )
    execution = ToolCallExecution(
        completed_at=datetime.now(UTC),
        output=mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(type="text", text="Error occurred"),
                mcp_types.ImageContent(
                    type="image", data="base64data", mimeType="image/png"
                ),
            ],
            isError=True,
        ),
    )
    record = ToolCallRecord(
        call_id="complex-call",
        run_id="complex-run",
        agent_id="complex-agent",
        tool_call=ToolCall(
            name="dangerous_operation",
            call_id="complex-call",
            args_json='{"action": "delete", "target": "/important/data"}',
        ),
        decision=decision,
        execution=execution,
    )

    # Save and retrieve
    await persistence.save_tool_call(record)
    retrieved = await persistence.get_tool_call("complex-call")

    # Verify all fields are preserved
    assert retrieved is not None
    assert retrieved.call_id == "complex-call"
    assert retrieved.run_id == "complex-run"
    assert retrieved.agent_id == "complex-agent"

    # Verify tool_call
    assert retrieved.tool_call.name == "dangerous_operation"
    assert retrieved.tool_call.args_json == '{"action": "delete", "target": "/important/data"}'

    # Verify decision
    assert retrieved.decision is not None
    assert retrieved.decision.outcome == ApprovalOutcome.USER_DENY_ABORT
    assert retrieved.decision.reason == "Security risk detected"

    # Verify execution
    assert retrieved.execution is not None
    assert retrieved.execution.output.isError is True
    assert len(retrieved.execution.output.content) == 2
    assert isinstance(retrieved.execution.output.content[0], mcp_types.TextContent)
    assert retrieved.execution.output.content[0].text == "Error occurred"
    assert isinstance(retrieved.execution.output.content[1], mcp_types.ImageContent)
    assert retrieved.execution.output.content[1].data == "base64data"
