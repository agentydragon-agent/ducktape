"""Tests for policy validation and reload functionality."""

from pathlib import Path

from docker import DockerClient
from fastmcp.mcp_config import MCPConfig
from hamcrest import assert_that, has_length, greater_than
import pytest

from adgn.agent.approvals import ApprovalPolicyEngine, load_default_policy_source
from adgn.agent.persist import AgentMetadata
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.mcp.approval_policy.server import ApprovalPolicyAdminServer, ReloadPolicyArgs, ValidatePolicyArgs

pytestmark = pytest.mark.requires_docker


@pytest.fixture
async def engine_and_persistence(tmp_path: Path, docker_client: DockerClient):
    """Create engine and persistence for testing."""
    db_path = tmp_path / "test.db"
    persistence = SQLitePersistence(db_path)
    await persistence.ensure_schema()

    # Create agent
    agent_id = await persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test"))

    # Create engine
    engine = ApprovalPolicyEngine(
        docker_client=docker_client,
        agent_id=agent_id,
        persistence=persistence,
        policy_source=load_default_policy_source(),
    )

    return engine, persistence


async def test_validate_policy_valid(engine_and_persistence, docker_client: DockerClient):
    """Test validating a valid policy."""
    engine, _ = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Valid Python code
    result = await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(source="print('hello')"))

    assert result.valid is True
    assert_that(result.errors, has_length(0))


async def test_validate_policy_syntax_error(engine_and_persistence):
    """Test validating a policy with syntax errors."""
    engine, _ = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Invalid syntax
    result = await admin_server._mcp_server._tools["validate_policy"].fn(ValidatePolicyArgs(source="print('hello'"))

    assert result.valid is False
    assert_that(result.errors, has_length(greater_than(0)))
    assert "Syntax error" in result.errors[0]


async def test_validate_policy_runtime_error(engine_and_persistence, docker_client: DockerClient):
    """Test validating a policy that fails at runtime."""
    engine, _ = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Syntactically valid but fails self-check (wrong structure)
    result = await admin_server._mcp_server._tools["validate_policy"].fn(
        ValidatePolicyArgs(source="import sys; sys.exit(1)")
    )

    assert result.valid is False
    assert_that(result.errors, has_length(greater_than(0)))
    assert "Runtime validation failed" in result.errors[0]


async def test_reload_policy_from_persistence(engine_and_persistence, docker_client: DockerClient):
    """Test reloading policy from persistence."""
    engine, persistence = engine_and_persistence

    # Save a policy to persistence
    new_policy = "print('from persistence')"
    await persistence.set_policy(engine.agent_id, content=new_policy)

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Change engine's in-memory policy
    engine.set_policy("print('different')")

    # Reload from persistence
    await admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=None))

    # Engine should now have the persisted policy
    current_policy, _ = engine.get_policy()
    assert current_policy == new_policy


async def test_reload_policy_from_source(engine_and_persistence, docker_client: DockerClient):
    """Test reloading policy from provided source."""
    engine, _ = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Reload with provided source
    new_source = load_default_policy_source()
    await admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=new_source))

    # Engine should have the new source
    current_policy, _ = engine.get_policy()
    assert current_policy == new_source


async def test_reload_policy_validates_source(engine_and_persistence, docker_client: DockerClient):
    """Test that reload validates the source before setting."""
    engine, _ = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Try to reload with invalid source
    with pytest.raises(Exception):  # Should fail validation
        await admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source="import sys; sys.exit(1)"))


async def test_reload_policy_no_persistence_raises(engine_and_persistence):
    """Test that reloading from empty persistence raises error."""
    engine, persistence = engine_and_persistence

    admin_server = ApprovalPolicyAdminServer(engine=engine)

    # Create a new agent with no policy in persistence
    new_agent_id = await persistence.create_agent(mcp_config=MCPConfig(), metadata=AgentMetadata(preset="test"))

    # Create new engine with no persisted policy
    new_engine = ApprovalPolicyEngine(
        docker_client=engine.docker_client,
        agent_id=new_agent_id,
        persistence=persistence,
        policy_source=load_default_policy_source(),
    )

    new_admin_server = ApprovalPolicyAdminServer(engine=new_engine)

    # Try to reload (should fail - no policy in persistence)
    with pytest.raises(ValueError, match="No policy found in persistence"):
        await new_admin_server._mcp_server._tools["reload_policy"].fn(ReloadPolicyArgs(source=None))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
