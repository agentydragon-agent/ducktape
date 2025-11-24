"""Shared fixtures for persistence layer tests.

Consolidates common setup across test_integration.py and test_sqlite_tool_calls.py
to reduce duplication and ensure consistency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mcp import types as mcp_types
import pytest

from adgn.agent.persist import ApprovalOutcome, Decision, ToolCall, ToolCallExecution
from adgn.agent.persist.sqlite import SQLitePersistence


@pytest.fixture
async def persistence(tmp_path: Path) -> SQLitePersistence:
    """Create a fresh SQLite persistence instance with schema.

    Shared by all persistence tests. Creates an in-memory database
    and ensures the schema is initialized.
    """
    db_path = tmp_path / "test.db"
    persist = SQLitePersistence(db_path)
    await persist.ensure_schema()
    return persist


@pytest.fixture
def sample_tool_call() -> ToolCall:
    """Create a sample tool call for testing.

    Shared by tests that need a standard tool call instance.
    """
    return ToolCall(name="test_tool", call_id="test-call-id", args_json='{"param1": "value1", "param2": 42}')


@pytest.fixture
def sample_decision() -> Decision:
    """Create a sample decision for testing.

    Shared by tests that need a standard decision instance.
    """
    return Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=datetime.now(UTC), reason="Automated approval")


@pytest.fixture
def sample_execution() -> ToolCallExecution:
    """Create a sample execution result for testing.

    Shared by tests that need a standard execution instance.
    """
    return ToolCallExecution(
        completed_at=datetime.now(UTC),
        output=mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="Success")], isError=False),
    )
