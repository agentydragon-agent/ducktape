"""MCP tests for policy validation.

Tests that PolicyEngine rejects policies with failing or missing tests.
"""

from __future__ import annotations

from fastmcp.client import Client
import pytest

from adgn.mcp.approval_policy.engine import PolicyEngine
from tests.agent.testdata.approval_policy import fetch_policy


@pytest.mark.requires_docker
class TestPolicyValidation:
    """Tests for policy validation via MCP admin tools."""

    @pytest.mark.asyncio
    async def test_set_policy_rejects_failing_tests(self, sqlite_persistence, docker_client):
        """Setting policy with failing tests raises an error."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# placeholder",
        )

        failing_policy = fetch_policy("failing_tests")

        async with Client(engine.admin) as sess:
            # Try to set policy via MCP tool - should fail
            result = await sess.call_tool("set_policy", {"source": failing_policy})
            # Tool should return error or raise
            assert result is not None
            # CallToolResult always has is_error - check for error
            assert result.is_error, "Expected error for failing tests policy"

    @pytest.mark.asyncio
    async def test_set_policy_accepts_valid_policy(self, sqlite_persistence, docker_client, policy_allow_all):
        """Setting valid policy succeeds."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# placeholder",
        )

        async with Client(engine.admin) as sess:
            result = await sess.call_tool("set_policy", {"source": policy_allow_all})
            # Should succeed - CallToolResult.is_error should be False
            assert result is not None
            assert not result.is_error

    @pytest.mark.asyncio
    async def test_create_proposal_validates_policy(self, sqlite_persistence, docker_client):
        """Creating proposal with failing tests raises an error."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# placeholder",
        )

        failing_policy = fetch_policy("failing_tests")

        async with Client(engine.policy_proposer) as sess:
            # Try to create proposal with failing policy - should fail validation
            try:
                result = await sess.call_tool("create_proposal", {"content": failing_policy})
                # If we get here without exception, result should indicate error
                if not result.is_error:
                    pytest.fail("Expected proposal creation to fail for policy with failing tests")
            except Exception:
                # Exception during validation is expected
                pass

    @pytest.mark.asyncio
    async def test_self_check_directly(self, sqlite_persistence, docker_client):
        """PolicyEngine.self_check raises for invalid policy."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# placeholder",
        )

        failing_policy = fetch_policy("failing_tests")

        # self_check should raise for policy with failing tests
        with pytest.raises(Exception):
            engine.self_check(failing_policy)

    @pytest.mark.asyncio
    async def test_self_check_passes_valid(self, sqlite_persistence, docker_client, policy_allow_all):
        """PolicyEngine.self_check passes for valid policy."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# placeholder",
        )

        # Should not raise
        engine.self_check(policy_allow_all)
