"""Tests for rollout analysis query builders.

Tests the query builders from critic_dev_util.examples.rollout_analysis.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from critic_dev_util.examples.rollout_analysis import (
    failed_tools_by_agent_run,
    tool_sequence_by_agent_run,
    tools_used_by_agent_run,
)
from props.db.config import DatabaseConfig
from props.db.session import get_session


@pytest.fixture
def db_session(synced_test_db: DatabaseConfig) -> Generator[Session, None, None]:
    """Provide a database session for testing."""
    with get_session() as session:
        yield session


class TestToolUsageQueries:
    """Test tool usage query builders."""

    def test_tools_used_by_agent_run_returns_select(self) -> None:
        """Verify tools_used_by_agent_run returns a Select object."""
        query = tools_used_by_agent_run(uuid4())
        assert query is not None

    def test_tool_sequence_by_agent_run_returns_select(self) -> None:
        """Verify tool_sequence_by_agent_run returns a Select object."""
        query = tool_sequence_by_agent_run(uuid4())
        assert query is not None

    def test_failed_tools_by_agent_run_returns_select(self) -> None:
        """Verify failed_tools_by_agent_run returns a Select object."""
        query = failed_tools_by_agent_run(uuid4())
        assert query is not None

    def test_tools_used_executes(self, db_session: Session) -> None:
        """Verify tools_used_by_agent_run executes without error."""
        query = tools_used_by_agent_run(uuid4())
        results = db_session.execute(query).fetchall()
        # No agent run exists, so empty results expected
        assert results == []

    def test_tool_sequence_executes(self, db_session: Session) -> None:
        """Verify tool_sequence_by_agent_run executes without error."""
        query = tool_sequence_by_agent_run(uuid4())
        results = db_session.execute(query).fetchall()
        assert results == []

    def test_failed_tools_executes(self, db_session: Session) -> None:
        """Verify failed_tools_by_agent_run executes without error."""
        query = failed_tools_by_agent_run(uuid4())
        results = db_session.execute(query).fetchall()
        assert results == []
