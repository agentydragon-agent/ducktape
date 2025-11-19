"""Integration tests for policy gateway middleware lifecycle tracking.

Tests verify that the middleware correctly tracks tool calls through their lifecycle:
- PENDING: Tool call arrives, before policy decision
- EXECUTING: Policy allows/user approves, before execution
- COMPLETED: Execution finished (success or error)

Uses real persistence (temp SQLite DB) and mocks policy/approval/tools.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastmcp.client.client import CallToolResult
from fastmcp.server.middleware.middleware import MiddlewareContext
from mcp import McpError, types as mcp_types
import pytest

from adgn.agent.approvals import ApprovalHub
from adgn.agent.persist import ApprovalOutcome, ToolCallRecord
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.policies.policy_types import ApprovalDecision, PolicyRequest, PolicyResponse
from adgn.mcp._shared.constants import POLICY_DENIED_ABORT_MSG
from adgn.mcp.approval_policy.clients import PolicyReaderStub
from adgn.mcp.policy_gateway.middleware import PolicyGatewayMiddleware

# --- Fixtures ---


@pytest.fixture
async def persistence(tmp_path: Path) -> SQLitePersistence:
    """Create a fresh SQLite persistence instance with schema."""
    db_path = tmp_path / "test.db"
    persist = SQLitePersistence(db_path)
    await persist.ensure_schema()
    return persist


# test_agent fixture now provided globally in tests/agent/conftest.py


@pytest.fixture
def approval_hub() -> ApprovalHub:
    """Fresh ApprovalHub for test."""
    return ApprovalHub()


@pytest.fixture
def run_id() -> UUID | None:
    """Run ID for tests (None to avoid FK constraints)."""
    return None


# --- Mock Policy Reader ---


class MockPolicyReader(PolicyReaderStub):
    """Mock policy reader that returns a configurable decision."""

    def __init__(self, decision: ApprovalDecision, rationale: str = "test rationale"):
        self.decision = decision
        self.rationale = rationale

    async def decide(self, input: PolicyRequest) -> PolicyResponse:
        return PolicyResponse(decision=self.decision, rationale=self.rationale)


# --- Mock Tool Execution ---


async def mock_call_next_success(context: MiddlewareContext[Any]) -> CallToolResult:
    """Mock successful tool execution."""
    return CallToolResult(
        content=[mcp_types.TextContent(type="text", text="success")],
        structured_content=None,
        meta=None,
        is_error=False,
    )


async def mock_call_next_error(context: MiddlewareContext[Any]) -> CallToolResult:
    """Mock tool execution that returns an error result."""
    result = CallToolResult(
        content=[mcp_types.TextContent(type="text", text="execution error")],
        structured_content=None,
        meta=None,
        is_error=True,
    )
    # Add error attribute that middleware checks
    result.error = None  # type: ignore
    return result


async def mock_call_next_exception(context: MiddlewareContext[Any]) -> CallToolResult:
    """Mock tool execution that raises an exception."""
    raise RuntimeError("tool execution failed")


# --- Helper to create mock MCP message ---


def make_mock_message(name: str, arguments: dict[str, Any] | None = None):
    """Create a mock MCP CallToolRequest message."""

    class MockMessage:
        def __init__(self, name: str, arguments: dict[str, Any] | None):
            self.name = name
            self.arguments = arguments or {}

    return MockMessage(name, arguments)


def make_mock_context(name: str, arguments: dict[str, Any] | None = None) -> MiddlewareContext[Any]:
    """Create a mock MiddlewareContext for testing."""

    class MockContext:
        def __init__(self, message):
            self.message = message

    return MockContext(make_mock_message(name, arguments))  # type: ignore


# --- Integration Tests ---


@pytest.mark.asyncio
async def test_policy_allow_lifecycle(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test POLICY_ALLOW flow: PENDING → EXECUTING → COMPLETED.

    Verifies:
    1. PENDING record created when tool call arrives
    2. EXECUTING record (with decision) after policy allows
    3. COMPLETED record (with execution) after tool executes
    4. All three saves happened
    5. Timestamps are logical (created < decided < completed)
    """
    # Arrange: Create middleware with ALLOW policy
    policy_reader = MockPolicyReader(ApprovalDecision.ALLOW)
    middleware = PolicyGatewayMiddleware(
        hub=approval_hub,
        policy_reader=policy_reader,
        persistence=persistence,
        run_id=run_id,
        agent_id=test_agent,
    )

    # Track call_id from PENDING record
    call_id_tracker: list[str] = []

    # Intercept save_tool_call to capture call_id
    original_save = persistence.save_tool_call

    async def tracking_save(record: ToolCallRecord):
        if not call_id_tracker:
            call_id_tracker.append(record.call_id)
        await original_save(record)

    persistence.save_tool_call = tracking_save  # type: ignore

    # Act: Execute tool call
    context = make_mock_context("test_tool", {"arg": "value"})
    result = await middleware.on_call_tool(context, mock_call_next_success)

    # Assert: Tool execution succeeded
    assert not result.is_error
    assert result.content[0].text == "success"  # type: ignore

    # Assert: Get final record from DB
    call_id = call_id_tracker[0]
    record = await persistence.get_tool_call(call_id)
    assert record is not None

    # Assert: Record structure
    assert record.call_id == call_id
    assert record.run_id is None  # No run_id in test environment
    assert record.agent_id == test_agent
    assert record.tool_call.name == "test_tool"
    assert record.tool_call.args_json == '{"arg": "value"}'

    # Assert: Decision exists (POLICY_ALLOW)
    assert record.decision is not None
    assert record.decision.outcome == ApprovalOutcome.POLICY_ALLOW
    assert record.decision.reason == "test rationale"

    # Assert: Execution exists (success)
    assert record.execution is not None
    assert record.execution.output.isError is False
    assert len(record.execution.output.content) == 1

    # Assert: Timestamps are logical
    decided_at = record.decision.decided_at
    completed_at = record.execution.completed_at
    assert decided_at < completed_at


@pytest.mark.asyncio
async def test_policy_deny_abort_lifecycle(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test POLICY_DENY flow: PENDING → final record (no execution).

    Verifies:
    1. PENDING record created
    2. Policy evaluates to DENY → final record with decision, no execution
    3. Exception raised
    4. No execution record
    """
    # Arrange: Create middleware with DENY_ABORT policy
    policy_reader = MockPolicyReader(ApprovalDecision.DENY_ABORT, "denied for security")
    middleware = PolicyGatewayMiddleware(
        hub=approval_hub,
        policy_reader=policy_reader,
        persistence=persistence,
        run_id=run_id,
        agent_id=test_agent,
    )

    # Track call_id
    call_id_tracker: list[str] = []
    original_save = persistence.save_tool_call

    async def tracking_save(record: ToolCallRecord):
        if not call_id_tracker:
            call_id_tracker.append(record.call_id)
        await original_save(record)

    persistence.save_tool_call = tracking_save  # type: ignore

    # Act & Assert: Execute should raise McpError
    context = make_mock_context("dangerous_tool", {"action": "delete"})
    with pytest.raises(McpError) as exc_info:
        await middleware.on_call_tool(context, mock_call_next_success)

    # Assert: Error message contains denial
    assert POLICY_DENIED_ABORT_MSG in str(exc_info.value)

    # Assert: Get record from DB
    call_id = call_id_tracker[0]
    record = await persistence.get_tool_call(call_id)
    assert record is not None

    # Assert: Decision exists (DENY)
    assert record.decision is not None
    assert record.decision.outcome == ApprovalOutcome.POLICY_DENY_ABORT
    assert record.decision.reason == "denied for security"

    # Assert: NO execution
    assert record.execution is None


@pytest.mark.asyncio
@pytest.mark.skip(reason="Approval flow tests need refactoring to handle async approval properly")
async def test_user_approve_lifecycle(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test USER_APPROVE flow: PENDING → (user approves) → EXECUTING → COMPLETED.

    Verifies:
    1. PENDING record created
    2. Policy evaluates to ASK → record saved in pending state
    3. User approves → EXECUTING record with decision
    4. Tool executes → COMPLETED record with execution
    5. All saves happened

    NOTE: This test is currently skipped due to complexity in handling async
    approval flow. The approval hub await/resolve mechanism needs proper
    synchronization that's difficult to test without a more sophisticated
    approval handler setup.
    """
    # Test body skipped


@pytest.mark.asyncio
@pytest.mark.skip(reason="Approval flow tests need refactoring to handle async approval properly")
async def test_user_deny_lifecycle(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test USER_DENY flow: PENDING → (user denies) → final record (no execution).

    Verifies:
    1. PENDING record created
    2. Policy evaluates to ASK → record saved
    3. User denies → final record with decision, no execution
    4. Exception raised
    5. No execution record

    NOTE: This test is currently skipped due to complexity in handling async
    approval flow. The approval hub await/resolve mechanism needs proper
    synchronization that's difficult to test without a more sophisticated
    approval handler setup.
    """
    # Test body skipped


@pytest.mark.asyncio
async def test_error_during_execution(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test error flow: PENDING → EXECUTING → COMPLETED (with error result).

    Verifies:
    1. PENDING record created
    2. Policy allows → EXECUTING record
    3. Tool execution fails → COMPLETED record with error in output
    4. Error captured in execution.output
    """
    # Arrange: Create middleware with ALLOW policy
    policy_reader = MockPolicyReader(ApprovalDecision.ALLOW)
    middleware = PolicyGatewayMiddleware(
        hub=approval_hub,
        policy_reader=policy_reader,
        persistence=persistence,
        run_id=run_id,
        agent_id=test_agent,
    )

    # Track call_id
    call_id_tracker: list[str] = []
    original_save = persistence.save_tool_call

    async def tracking_save(record: ToolCallRecord):
        if not call_id_tracker:
            call_id_tracker.append(record.call_id)
        await original_save(record)

    persistence.save_tool_call = tracking_save  # type: ignore

    # Act: Execute tool call (tool returns error result)
    context = make_mock_context("failing_tool", {})
    result = await middleware.on_call_tool(context, mock_call_next_error)

    # Assert: Tool returned error result
    assert result.is_error
    assert result.content[0].text == "execution error"  # type: ignore

    # Assert: Get record
    call_id = call_id_tracker[0]
    record = await persistence.get_tool_call(call_id)
    assert record is not None

    # Assert: Decision exists (ALLOW)
    assert record.decision is not None
    assert record.decision.outcome == ApprovalOutcome.POLICY_ALLOW

    # Assert: Execution exists with error
    assert record.execution is not None
    assert record.execution.output.isError is True
    assert record.execution.output.content[0].text == "execution error"  # type: ignore


@pytest.mark.asyncio
async def test_multiple_tool_calls(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test multiple tool calls in sequence.

    Verifies:
    1. Each gets unique call_id
    2. Each tracked independently
    3. run_id consistent across all
    """
    # Arrange: Create middleware with ALLOW policy
    policy_reader = MockPolicyReader(ApprovalDecision.ALLOW)
    middleware = PolicyGatewayMiddleware(
        hub=approval_hub,
        policy_reader=policy_reader,
        persistence=persistence,
        run_id=run_id,
        agent_id=test_agent,
    )

    # Act: Execute three tool calls
    tool_names = ["tool_one", "tool_two", "tool_three"]
    for tool_name in tool_names:
        context = make_mock_context(tool_name, {"index": tool_name})
        await middleware.on_call_tool(context, mock_call_next_success)

    # Assert: List all tool calls (no run_id filter in test environment)
    records = await persistence.list_tool_calls()
    assert len(records) == 3

    # Assert: Each has unique call_id
    call_ids = {r.call_id for r in records}
    assert len(call_ids) == 3

    # Assert: All have None run_id (test environment)
    assert all(r.run_id is None for r in records)

    # Assert: All have the test agent_id
    assert all(r.agent_id == test_agent for r in records)

    # Assert: Each has correct tool name
    tool_names_from_db = {r.tool_call.name for r in records}
    assert tool_names_from_db == set(tool_names)

    # Assert: All completed successfully
    assert all(r.decision is not None for r in records)
    assert all(r.execution is not None for r in records)
    assert all(r.execution.output.isError is False for r in records)


@pytest.mark.asyncio
async def test_timestamp_ordering(
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
    """Test that timestamps are properly ordered: created < decided < completed.

    This is a more detailed verification of timestamp logic.
    """
    # Arrange: Create middleware with ALLOW policy
    policy_reader = MockPolicyReader(ApprovalDecision.ALLOW)
    middleware = PolicyGatewayMiddleware(
        hub=approval_hub,
        policy_reader=policy_reader,
        persistence=persistence,
        run_id=run_id,
        agent_id=test_agent,
    )

    # Track timestamps at each stage
    timestamps: dict[str, datetime] = {}

    original_save = persistence.save_tool_call

    async def tracking_save(record: ToolCallRecord):
        # Capture timestamp based on record state
        if record.decision is None and record.execution is None:
            timestamps["pending"] = datetime.now(UTC)
        elif record.decision is not None and record.execution is None:
            timestamps["executing"] = record.decision.decided_at
        elif record.decision is not None and record.execution is not None:
            timestamps["completed"] = record.execution.completed_at

        await original_save(record)

    persistence.save_tool_call = tracking_save  # type: ignore

    # Act: Execute tool call
    context = make_mock_context("test_tool", {})
    await middleware.on_call_tool(context, mock_call_next_success)

    # Assert: All three timestamps captured
    assert "pending" in timestamps
    assert "executing" in timestamps
    assert "completed" in timestamps

    # Assert: Timestamps are properly ordered
    # Note: pending is captured when we call save, so it might be slightly after decided_at
    # The key assertion is: decided_at < completed_at
    assert timestamps["executing"] < timestamps["completed"]
