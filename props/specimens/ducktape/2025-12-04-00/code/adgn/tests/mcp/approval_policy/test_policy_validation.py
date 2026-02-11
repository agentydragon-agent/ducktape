"""MCP tests for policy validation.

Tests that PolicyEngine rejects policies with failing or missing tests.
"""

from __future__ import annotations

from fastmcp.client import Client
import pytest

from adgn.mcp.approval_policy.engine import PolicyEngine
from tests.agent.testdata.approval_policy import fetch_policy


@pytest.fixture
def policy_engine(sqlite_persistence, docker_client) -> PolicyEngine:
    """PolicyEngine instance for validation tests."""
    return PolicyEngine(
        docker_client=docker_client,
        agent_id="test-agent",
        persistence=sqlite_persistence,
        policy_source="# placeholder",
    )


@pytest.fixture
def failing_policy() -> str:
    """Policy source with failing tests."""
    result: str = fetch_policy("failing_tests")
    return result


@pytest.mark.requires_docker
class TestPolicyValidation:
    """Tests for policy validation via MCP admin tools."""

    @pytest.mark.asyncio
    async def test_set_policy_rejects_failing_tests(self, policy_engine, failing_policy):
        """Setting policy with failing tests raises an error."""
        async with Client(policy_engine.admin) as sess:
            result = await sess.call_tool("set_policy", {"source": failing_policy})
            assert result.is_error, "Expected error for failing tests policy"

    @pytest.mark.asyncio
    async def test_set_policy_accepts_valid_policy(self, policy_engine, policy_allow_all):
        """Setting valid policy succeeds."""
        async with Client(policy_engine.admin) as sess:
            result = await sess.call_tool("set_policy", {"source": policy_allow_all})
            assert not result.is_error

    @pytest.mark.asyncio
    async def test_create_proposal_validates_policy(self, policy_engine, failing_policy):
        """Creating proposal with failing tests returns error."""
        async with Client(policy_engine.policy_proposer) as sess:
            result = await sess.call_tool("create_proposal", {"content": failing_policy})
            assert result.is_error, "Expected error for policy with failing tests"

    @pytest.mark.asyncio
    async def test_self_check_directly(self, policy_engine, failing_policy):
        """PolicyEngine.self_check raises for invalid policy."""
        with pytest.raises(RuntimeError, match="policy eval failed"):
            policy_engine.self_check(failing_policy)

    @pytest.mark.asyncio
    async def test_self_check_passes_valid(self, policy_engine, policy_allow_all):
        """PolicyEngine.self_check passes for valid policy."""
        policy_engine.self_check(policy_allow_all)
