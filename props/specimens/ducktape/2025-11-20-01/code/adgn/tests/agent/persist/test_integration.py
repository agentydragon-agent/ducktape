"""Comprehensive integration tests for the persistence layer covering all lifecycle states.

This test suite validates the complete tool call lifecycle through the persistence layer:
- PENDING (no decision, no execution)
- EXECUTING (decision present, no execution)
- COMPLETED (decision and execution both present)

It also tests:
- Multiple concurrent tool calls
- State transition validation
- Decision outcome variants
- Complex CallToolResult content types
- Concurrent access patterns
- Error handling and data corruption scenarios
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from hamcrest import assert_that, has_length, instance_of
from mcp import types as mcp_types
import pytest

from adgn.agent.persist import ToolCallRecord, ToolCall, Decision, ToolCallExecution
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.persist import ApprovalOutcome

# test_agent fixture now provided globally in tests/agent/conftest.py
# persistence, sample_tool_call, sample_decision, sample_execution fixtures
# are now provided by tests/agent/persist/conftest.py


# Test 1: Full lifecycle test
@pytest.mark.asyncio
async def test_full_lifecycle_with_timestamp_preservation(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test complete lifecycle: PENDING → EXECUTING → COMPLETED with timestamp preservation.

    Validates that all three states can be saved and retrieved, and that timestamps
    are preserved correctly throughout the lifecycle.
    """
    call_id = "lifecycle-test-call"
    run_id = "lifecycle-test-run"
    agent_id = "lifecycle-test-agent"

    # Phase 1: Create and save PENDING record
    pending_record = ToolCallRecord(
        call_id=call_id,
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="lifecycle_tool", call_id=call_id, args_json='{"step": "start"}'),
        decision=None,
        execution=None,
    )
    await persistence.save_tool_call(pending_record)

    # Retrieve and verify PENDING state
    retrieved_pending = await persistence.get_tool_call(call_id)
    assert retrieved_pending is not None
    assert retrieved_pending.decision is None
    assert retrieved_pending.execution is None
    assert retrieved_pending.tool_call.name == "lifecycle_tool"

    # Phase 2: Update to EXECUTING (add decision)
    decision_time = datetime.now(UTC)
    decision = Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=decision_time, reason="User approved manually")
    executing_record = ToolCallRecord(
        call_id=call_id,
        run_id=None,
        agent_id=test_agent,
        tool_call=pending_record.tool_call,
        decision=decision,
        execution=None,
    )
    await persistence.save_tool_call(executing_record)

    # Retrieve and verify EXECUTING state
    retrieved_executing = await persistence.get_tool_call(call_id)
    assert retrieved_executing is not None
    assert retrieved_executing.decision is not None
    assert retrieved_executing.decision.outcome == ApprovalOutcome.USER_APPROVE
    assert retrieved_executing.decision.decided_at == decision_time
    assert retrieved_executing.execution is None

    # Phase 3: Update to COMPLETED (add execution)
    completion_time = datetime.now(UTC)
    execution = ToolCallExecution(
        completed_at=completion_time,
        output=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Lifecycle completed successfully")], isError=False
        ),
    )
    completed_record = ToolCallRecord(
        call_id=call_id,
        run_id=None,
        agent_id=test_agent,
        tool_call=pending_record.tool_call,
        decision=decision,
        execution=execution,
    )
    await persistence.save_tool_call(completed_record)

    # Retrieve and verify COMPLETED state with all timestamps preserved
    retrieved_completed = await persistence.get_tool_call(call_id)
    assert retrieved_completed is not None
    assert retrieved_completed.decision is not None
    assert retrieved_completed.decision.decided_at == decision_time
    assert retrieved_completed.execution is not None
    assert retrieved_completed.execution.completed_at == completion_time
    assert retrieved_completed.execution.output.content[0].text == "Lifecycle completed successfully"


# Test 2: Multiple tool calls test
@pytest.mark.asyncio
async def test_multiple_tool_calls_with_different_states(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test saving multiple tool calls with different states.

    Creates 5 tool calls with varying states (PENDING, EXECUTING, COMPLETED), then validates:
    - Correct total count
    - Each record is retrievable
    - States are preserved correctly
    """
    # Create 5 tool calls with different states
    records = [
        # PENDING
        ToolCallRecord(
            call_id="multi-1",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name="tool_a", call_id="multi-1", args_json='{"id": 1}'),
            decision=None,
            execution=None,
        ),
        # EXECUTING
        ToolCallRecord(
            call_id="multi-2",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name="tool_b", call_id="multi-2", args_json='{"id": 2}'),
            decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
            execution=None,
        ),
        # COMPLETED
        ToolCallRecord(
            call_id="multi-3",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name="tool_c", call_id="multi-3", args_json='{"id": 3}'),
            decision=Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=datetime.now(UTC), reason=None),
            execution=ToolCallExecution(
                completed_at=datetime.now(UTC),
                output=mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text="Done")], isError=False
                ),
            ),
        ),
        # PENDING (another one)
        ToolCallRecord(
            call_id="multi-4",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name="tool_d", call_id="multi-4", args_json='{"id": 4}'),
            decision=None,
            execution=None,
        ),
        # EXECUTING (another one)
        ToolCallRecord(
            call_id="multi-5",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name="tool_e", call_id="multi-5", args_json='{"id": 5}'),
            decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
            execution=None,
        ),
    ]

    # Save all records
    for record in records:
        await persistence.save_tool_call(record)

    # Test 1: List all tool calls
    all_calls = await persistence.list_tool_calls()
    assert_that(all_calls, has_length(5))
    assert {r.call_id for r in all_calls} == {"multi-1", "multi-2", "multi-3", "multi-4", "multi-5"}

    # Test 2: Verify each state is preserved
    multi1 = await persistence.get_tool_call("multi-1")
    assert multi1 is not None
    assert multi1.decision is None and multi1.execution is None  # PENDING

    multi2 = await persistence.get_tool_call("multi-2")
    assert multi2 is not None
    assert multi2.decision is not None and multi2.execution is None  # EXECUTING

    multi3 = await persistence.get_tool_call("multi-3")
    assert multi3 is not None
    assert multi3.decision is not None and multi3.execution is not None  # COMPLETED

    # Test 3: Verify ordering (should be by created_at ASC)
    assert [r.call_id for r in all_calls] == ["multi-1", "multi-2", "multi-3", "multi-4", "multi-5"]


# Test 3: State transitions test
@pytest.mark.asyncio
async def test_state_transitions_validation(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test valid and invalid state transitions.

    Valid transitions:
    - PENDING → EXECUTING (add decision)
    - EXECUTING → COMPLETED (add execution)
    - PENDING → COMPLETED (skip EXECUTING if policy auto-executes)

    This test doesn't enforce invalid transitions at the persistence layer
    (that's application logic), but validates that the persistence layer
    correctly stores whatever state is provided.
    """
    # Valid transition 1: PENDING → EXECUTING
    record1 = ToolCallRecord(
        call_id="trans-1",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="tool_1", call_id="trans-1", args_json="{}"),
        decision=None,
        execution=None,
    )
    await persistence.save_tool_call(record1)

    # Add decision (PENDING → EXECUTING)
    record1_executing = ToolCallRecord(
        call_id="trans-1",
        run_id=None,
        agent_id=test_agent,
        tool_call=record1.tool_call,
        decision=Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=datetime.now(UTC), reason=None),
        execution=None,
    )
    await persistence.save_tool_call(record1_executing)
    retrieved = await persistence.get_tool_call("trans-1")
    assert retrieved is not None
    assert retrieved.decision is not None
    assert retrieved.execution is None

    # Valid transition 2: EXECUTING → COMPLETED
    record1_completed = ToolCallRecord(
        call_id="trans-1",
        run_id=None,
        agent_id=test_agent,
        tool_call=record1.tool_call,
        decision=record1_executing.decision,
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="OK")], isError=False),
        ),
    )
    await persistence.save_tool_call(record1_completed)
    retrieved = await persistence.get_tool_call("trans-1")
    assert retrieved is not None
    assert retrieved.decision is not None
    assert retrieved.execution is not None

    # Valid transition 3: PENDING → COMPLETED (skip EXECUTING for auto-approved)
    record2 = ToolCallRecord(
        call_id="trans-2",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="tool_2", call_id="trans-2", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Auto-executed")], isError=False
            ),
        ),
    )
    await persistence.save_tool_call(record2)
    retrieved = await persistence.get_tool_call("trans-2")
    assert retrieved is not None
    assert retrieved.decision is not None
    assert retrieved.execution is not None

    # Note: Persistence layer doesn't enforce invalid transitions (e.g., COMPLETED → PENDING)
    # That's application logic. The persistence layer just stores what it's given.


# Test 4: Decision outcome variants test
@pytest.mark.asyncio
async def test_decision_outcome_variants(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test all decision outcome types and their execution patterns.

    Tests:
    - POLICY_ALLOW → successful execution
    - POLICY_DENY_ABORT → no execution
    - USER_APPROVE → successful execution
    - USER_DENY_ABORT → no execution
    - USER_DENY_CONTINUE → no execution but could continue
    - POLICY_DENY_CONTINUE → no execution but could continue
    """
    outcomes_to_test = [
        (ApprovalOutcome.POLICY_ALLOW, True, "Policy auto-approved and executed"),
        (ApprovalOutcome.POLICY_DENY_ABORT, False, "Policy denied, aborted"),
        (ApprovalOutcome.USER_APPROVE, True, "User approved, executed"),
        (ApprovalOutcome.USER_DENY_ABORT, False, "User denied, aborted"),
        (ApprovalOutcome.USER_DENY_CONTINUE, False, "User denied but continued"),
        (ApprovalOutcome.POLICY_DENY_CONTINUE, False, "Policy denied but continued"),
    ]

    for i, (outcome, should_execute, reason) in enumerate(outcomes_to_test):
        call_id = f"outcome-{i}"
        decision = Decision(outcome=outcome, decided_at=datetime.now(UTC), reason=reason)

        if should_execute:
            # Create COMPLETED record with execution
            record = ToolCallRecord(
                call_id=call_id,
                run_id=None,
                agent_id=test_agent,
                tool_call=ToolCall(name=f"tool_{i}", call_id=call_id, args_json="{}"),
                decision=decision,
                execution=ToolCallExecution(
                    completed_at=datetime.now(UTC),
                    output=mcp_types.CallToolResult(
                        content=[mcp_types.TextContent(type="text", text=f"Executed for {outcome}")], isError=False
                    ),
                ),
            )
        else:
            # Create EXECUTING record without execution (denied)
            record = ToolCallRecord(
                call_id=call_id,
                run_id=None,
                agent_id=test_agent,
                tool_call=ToolCall(name=f"tool_{i}", call_id=call_id, args_json="{}"),
                decision=decision,
                execution=None,
            )

        await persistence.save_tool_call(record)

        # Verify
        retrieved = await persistence.get_tool_call(call_id)
        assert retrieved is not None
        assert retrieved.decision is not None
        assert retrieved.decision.outcome == outcome
        assert retrieved.decision.reason == reason

        if should_execute:
            assert retrieved.execution is not None
        else:
            assert retrieved.execution is None


# Test 5: Complex CallToolResult test
@pytest.mark.asyncio
async def test_complex_calltoolresult_content_types(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test persistence of complex CallToolResult with multiple content types.

    Tests:
    - Text content
    - Image content
    - Error content
    - Mixed content (multiple items)
    - Empty content
    """
    # Test 1: Text content
    record1 = ToolCallRecord(
        call_id="content-text",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="text_tool", call_id="content-text", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Simple text output")], isError=False
            ),
        ),
    )
    await persistence.save_tool_call(record1)
    retrieved1 = await persistence.get_tool_call("content-text")
    assert retrieved1 is not None
    assert_that(retrieved1.execution.output.content, has_length(1))
    assert_that(retrieved1.execution.output.content[0], instance_of(mcp_types.TextContent))
    assert retrieved1.execution.output.content[0].text == "Simple text output"

    # Test 2: Image content
    record2 = ToolCallRecord(
        call_id="content-image",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="image_tool", call_id="content-image", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[
                    mcp_types.ImageContent(
                        type="image",
                        data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                        mimeType="image/png",
                    )
                ],
                isError=False,
            ),
        ),
    )
    await persistence.save_tool_call(record2)
    retrieved2 = await persistence.get_tool_call("content-image")
    assert retrieved2 is not None
    assert_that(retrieved2.execution.output.content, has_length(1))
    assert_that(retrieved2.execution.output.content[0], instance_of(mcp_types.ImageContent))
    assert retrieved2.execution.output.content[0].mimeType == "image/png"

    # Test 3: Error content
    record3 = ToolCallRecord(
        call_id="content-error",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="error_tool", call_id="content-error", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Error: File not found")], isError=True
            ),
        ),
    )
    await persistence.save_tool_call(record3)
    retrieved3 = await persistence.get_tool_call("content-error")
    assert retrieved3 is not None
    assert retrieved3.execution.output.isError is True
    assert retrieved3.execution.output.content[0].text == "Error: File not found"

    # Test 4: Mixed content (text + image)
    record4 = ToolCallRecord(
        call_id="content-mixed",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="mixed_tool", call_id="content-mixed", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[
                    mcp_types.TextContent(type="text", text="Generated visualization:"),
                    mcp_types.ImageContent(type="image", data="base64data", mimeType="image/svg+xml"),
                    mcp_types.TextContent(type="text", text="Analysis complete."),
                ],
                isError=False,
            ),
        ),
    )
    await persistence.save_tool_call(record4)
    retrieved4 = await persistence.get_tool_call("content-mixed")
    assert retrieved4 is not None
    assert_that(retrieved4.execution.output.content, has_length(3))
    assert_that(retrieved4.execution.output.content[0], instance_of(mcp_types.TextContent))
    assert_that(retrieved4.execution.output.content[1], instance_of(mcp_types.ImageContent))
    assert_that(retrieved4.execution.output.content[2], instance_of(mcp_types.TextContent))

    # Test 5: Empty content (edge case)
    record5 = ToolCallRecord(
        call_id="content-empty",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="empty_tool", call_id="content-empty", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC), output=mcp_types.CallToolResult(content=[], isError=False)
        ),
    )
    await persistence.save_tool_call(record5)
    retrieved5 = await persistence.get_tool_call("content-empty")
    assert retrieved5 is not None
    assert_that(retrieved5.execution.output.content, has_length(0))


# Test 6: Concurrent access test
@pytest.mark.asyncio
async def test_concurrent_access_and_data_integrity(persistence: SQLitePersistence, test_agent: str) -> None:
    """Test concurrent access patterns to ensure no data corruption.

    Simulates multiple async tasks saving different tool calls simultaneously.
    Validates that all saves succeed and data remains consistent.
    """

    async def save_tool_call_task(index: int) -> None:
        """Task that saves a tool call."""
        record = ToolCallRecord(
            call_id=f"concurrent-{index}",
            run_id=None,
            agent_id=test_agent,
            tool_call=ToolCall(name=f"tool_{index}", call_id=f"concurrent-{index}", args_json=f'{{"index": {index}}}'),
            decision=Decision(
                outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=f"Concurrent task {index}"
            ),
            execution=ToolCallExecution(
                completed_at=datetime.now(UTC),
                output=mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text=f"Result {index}")], isError=False
                ),
            ),
        )
        await persistence.save_tool_call(record)

    # Launch 20 concurrent save operations
    async with asyncio.TaskGroup() as tg:
        for i in range(20):
            tg.create_task(save_tool_call_task(i))

    # Verify all 20 records were saved
    all_calls = await persistence.list_tool_calls()
    assert_that(all_calls, has_length(20))

    # Verify no data corruption - each call_id should be unique
    call_ids = {r.call_id for r in all_calls}
    assert_that(call_ids, has_length(20))
    assert call_ids == {f"concurrent-{i}" for i in range(20)}

    # Verify each record is intact by retrieving individually
    for i in range(20):
        retrieved = await persistence.get_tool_call(f"concurrent-{i}")
        assert retrieved is not None
        assert retrieved.tool_call.name == f"tool_{i}"
        assert retrieved.decision is not None
        assert retrieved.decision.reason == f"Concurrent task {i}"
        assert retrieved.execution is not None
        assert retrieved.execution.output.content[0].text == f"Result {i}"


# Test 7: Error handling test
@pytest.mark.asyncio
async def test_error_handling_and_data_validation(tmp_path: Path, test_agent: str) -> None:
    """Test error handling for invalid data scenarios.

    Tests:
    - Invalid JSON in database (manual corruption)
    - Missing required fields
    - Malformed data
    """
    db_path = tmp_path / "error_test.db"
    persist = SQLitePersistence(db_path)
    await persist.ensure_schema()

    # Create a test agent using ORM
    from adgn.agent.persist.models import Agent

    async with persist._session() as session:
        agent = Agent(
            id=test_agent,
            created_at=datetime.now(UTC),
            mcp_config={},
            preset="test",
        )
        session.add(agent)
        await session.commit()

    # First, save a valid record
    valid_record = ToolCallRecord(
        call_id="valid-call",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="valid_tool", call_id="valid-call", args_json="{}"),
        decision=None,
        execution=None,
    )
    await persist.save_tool_call(valid_record)

    # Test 1: Manually corrupt the JSON in the database
    from sqlalchemy import text

    async with persist._session() as session:
        await session.execute(
            text("UPDATE tool_calls SET tool_call_json = :json WHERE call_id = :call_id"),
            {"json": '{"invalid json syntax', "call_id": "valid-call"},
        )
        await session.commit()

    # Attempting to retrieve should raise an error
    with pytest.raises(Exception):  # Could be JSONDecodeError or Pydantic validation error
        await persist.get_tool_call("valid-call")

    # Test 2: Insert record with missing required field in JSON
    async with persist._session() as session:
        # Insert a record missing the 'name' field in tool_call
        await session.execute(
            text("""
            INSERT INTO tool_calls (
                call_id, run_id, agent_id, tool_call_json,
                decision_json, execution_json,
                created_at, decided_at, completed_at
            ) VALUES (:call_id, :run_id, :agent_id, :tool_call_json, :decision_json, :execution_json, :created_at, :decided_at, :completed_at)
            """),
            {
                "call_id": "missing-field",
                "run_id": None,
                "agent_id": test_agent,
                "tool_call_json": '{"call_id": "missing-field"}',  # Missing 'name' field
                "decision_json": None,
                "execution_json": None,
                "created_at": datetime.now(UTC).isoformat(),
                "decided_at": None,
                "completed_at": None,
            },
        )
        await session.commit()

    # Attempting to retrieve should raise a validation error
    with pytest.raises(Exception):  # Pydantic ValidationError
        await persist.get_tool_call("missing-field")

    # Test 3: Get non-existent call_id (should return None, not raise)
    result = await persist.get_tool_call("non-existent-id")
    assert result is None

    # Test 4: Test with malformed timestamp
    async with persist._session() as session:
        await session.execute(
            text("""
            INSERT INTO tool_calls (
                call_id, run_id, agent_id, tool_call_json,
                decision_json, execution_json,
                created_at, decided_at, completed_at
            ) VALUES (:call_id, :run_id, :agent_id, :tool_call_json, :decision_json, :execution_json, :created_at, :decided_at, :completed_at)
            """),
            {
                "call_id": "bad-timestamp",
                "run_id": None,
                "agent_id": test_agent,
                "tool_call_json": '{"name": "tool", "call_id": "bad-timestamp"}',
                "decision_json": '{"outcome": "policy_allow", "decided_at": "not-a-timestamp", "reason": null}',
                "execution_json": None,
                "created_at": datetime.now(UTC).isoformat(),
                "decided_at": "not-a-timestamp",  # Invalid timestamp
                "completed_at": None,
            },
        )
        await session.commit()

    # Attempting to retrieve should raise an error
    with pytest.raises(Exception):  # Could be ValueError or Pydantic validation error
        await persist.get_tool_call("bad-timestamp")


# Summary test: Verify all lifecycle states exist in a single run
@pytest.mark.asyncio
async def test_summary_all_states_in_single_run(persistence: SQLitePersistence, test_agent: str) -> None:
    """Summary test showing all three states coexisting in a single run.

    This demonstrates a realistic scenario where a single agent run has:
    - Some tool calls still pending approval
    - Some approved but executing
    - Some completed
    """
    # Create PENDING call
    pending = ToolCallRecord(
        call_id="summary-pending",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="pending_tool", call_id="summary-pending", args_json="{}"),
        decision=None,
        execution=None,
    )
    await persistence.save_tool_call(pending)

    # Create EXECUTING call
    executing = ToolCallRecord(
        call_id="summary-executing",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="executing_tool", call_id="summary-executing", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=datetime.now(UTC), reason=None),
        execution=None,
    )
    await persistence.save_tool_call(executing)

    # Create COMPLETED call
    completed = ToolCallRecord(
        call_id="summary-completed",
        run_id=None,
        agent_id=test_agent,
        tool_call=ToolCall(name="completed_tool", call_id="summary-completed", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason=None),
        execution=ToolCallExecution(
            completed_at=datetime.now(UTC),
            output=mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Completed")], isError=False
            ),
        ),
    )
    await persistence.save_tool_call(completed)

    # List all calls
    all_calls = await persistence.list_tool_calls()
    assert_that(all_calls, has_length(3))

    # Verify each state is present
    call_states = {r.call_id: (r.decision is not None, r.execution is not None) for r in all_calls}
    assert call_states["summary-pending"] == (False, False)  # PENDING
    assert call_states["summary-executing"] == (True, False)  # EXECUTING
    assert call_states["summary-completed"] == (True, True)  # COMPLETED
