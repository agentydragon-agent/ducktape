"""Tests for agent_registry module."""

import pytest

from adgn.props.agent_registry import make_type_config
from adgn.props.agent_types import AgentType


class TestMakeTypeConfig:
    """Tests for make_type_config helper."""

    def test_includes_agent_type_key(self) -> None:
        """Result includes agent_type key derived from enum."""
        result = make_type_config(AgentType.CRITIC)
        assert result["agent_type"] == "critic"

    def test_merges_kwargs(self) -> None:
        """Additional kwargs are merged into result."""
        result = make_type_config(AgentType.CRITIC, snapshot_slug="test/snapshot", scope_hash="abc123")
        assert result == {"agent_type": "critic", "snapshot_slug": "test/snapshot", "scope_hash": "abc123"}

    @pytest.mark.parametrize(
        ("agent_type", "expected"),
        [
            (AgentType.CRITIC, "critic"),
            (AgentType.GRADER, "grader"),
            (AgentType.PROMPT_OPTIMIZER, "prompt_optimizer"),
            (AgentType.CLUSTERING, "clustering"),
            (AgentType.FREEFORM, "freeform"),
        ],
    )
    def test_all_agent_types_produce_correct_value(self, agent_type: AgentType, expected: str) -> None:
        """All AgentType enum values produce expected string."""
        result = make_type_config(agent_type)
        assert result["agent_type"] == expected


# AgentRegistry tests requiring database + MCP infrastructure are deferred
# to e2e/integration tests since they need:
# - Populated agent_definitions table
# - MCP client and compositor setup
# - Mock or real LLM client
#
# The registry's stateless helpers like make_type_config are unit-testable above.
