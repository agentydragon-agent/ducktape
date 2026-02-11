"""MCP tests for preset policy loading.

Tests that policy is correctly loaded from presets and accessible via MCP resources.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
from mcp.types import TextContent
import pytest

from adgn.agent.presets import create_agent_from_preset, discover_presets
from adgn.mcp._shared.constants import APPROVAL_POLICY_RESOURCE_URI
from adgn.mcp.approval_policy.engine import PolicyEngine
from tests.agent.testdata.approval_policy import fetch_policy


class TestPresetPolicyDiscovery:
    """Tests for preset policy discovery."""

    def test_discover_presets_includes_default(self):
        """discover_presets always includes default preset."""
        presets = discover_presets()
        assert "default" in presets
        assert presets["default"].name == "default"

    def test_discover_presets_from_directory(self, tmp_path: Path):
        """discover_presets loads from specified directory."""
        # Create a test preset file
        preset_file = tmp_path / "custom.yaml"
        preset_file.write_text("""
name: custom
description: A custom preset
approval_policy: |
    # Custom policy
    from adgn.agent.policies.policy_types import PolicyRequest, PolicyResponse, ApprovalDecision
    from adgn.agent.policies.scaffold import run

    def decide(req: PolicyRequest) -> PolicyResponse:
        return PolicyResponse(decision=ApprovalDecision.ALLOW, rationale="custom")

    if __name__ == "__main__":
        raise SystemExit(run(decide))
""")

        presets = discover_presets(override_dir=tmp_path)
        assert "custom" in presets
        assert presets["custom"].approval_policy is not None
        assert "custom" in presets["custom"].approval_policy.lower()


@pytest.mark.requires_docker
class TestPresetPolicyLoading:
    """Tests that preset policies are correctly loaded into PolicyEngine."""

    @pytest.mark.asyncio
    async def test_policy_engine_uses_provided_source(self, sqlite_persistence, docker_client, policy_allow_all):
        """PolicyEngine exposes the provided policy_source via resource."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source=policy_allow_all,
        )

        async with Client(engine.reader) as sess:
            # Read the policy resource
            contents = await sess.read_resource(str(APPROVAL_POLICY_RESOURCE_URI))
            assert contents is not None
            text_parts = [c for c in contents if isinstance(c, TextContent)]
            assert len(text_parts) >= 1
            # Should contain the allow_all policy
            policy_text = text_parts[0].text
            assert "approve_all" in policy_text.lower() or "allow" in policy_text.lower()

    @pytest.mark.asyncio
    async def test_policy_engine_returns_custom_policy(self, sqlite_persistence, docker_client):
        """PolicyEngine correctly returns custom policy source."""
        custom_policy = fetch_policy("const")

        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source=custom_policy,
        )

        async with Client(engine.reader) as sess:
            contents = await sess.read_resource(str(APPROVAL_POLICY_RESOURCE_URI))
            text_parts = [c for c in contents if isinstance(c, TextContent)]
            policy_text = text_parts[0].text
            # const policy should be returned
            assert "const" in policy_text.lower() or "PolicyResponse" in policy_text

    @pytest.mark.asyncio
    async def test_get_policy_returns_source_and_version(self, sqlite_persistence, docker_client, policy_allow_all):
        """PolicyEngine.get_policy returns (source, version)."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source=policy_allow_all,
        )

        source, version = engine.get_policy()
        assert source == policy_allow_all
        assert version == 1  # Initial version

    @pytest.mark.asyncio
    async def test_set_policy_increments_version(self, sqlite_persistence, docker_client, policy_allow_all):
        """PolicyEngine.set_policy increments version."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# initial",
        )

        _, initial_version = engine.get_policy()
        assert initial_version == 1

        # Set a new valid policy (self_check runs, needs valid policy)
        engine.set_policy(policy_allow_all)

        new_source, new_version = engine.get_policy()
        assert new_source == policy_allow_all
        assert new_version == 2

    @pytest.mark.asyncio
    async def test_load_policy_sets_without_incrementing(self, sqlite_persistence, docker_client, policy_allow_all):
        """PolicyEngine.load_policy sets policy at specific version (hydration)."""
        engine = PolicyEngine(
            docker_client=docker_client,
            agent_id="test-agent",
            persistence=sqlite_persistence,
            policy_source="# initial",
        )

        # load_policy is for hydration from persistence
        engine.load_policy(policy_allow_all, version=42)

        source, version = engine.get_policy()
        assert source == policy_allow_all
        assert version == 42


class TestPresetPolicyResolution:
    """Tests for preset policy resolution logic."""

    @pytest.mark.asyncio
    async def test_agent_metadata_records_preset(self, sqlite_persistence):
        """Creating agent from preset records preset name in metadata."""
        agent_id, _config, _system = await create_agent_from_preset(
            persistence=sqlite_persistence, preset_name="default", base_mcp_config=MCPConfig(mcpServers={})
        )

        # Check that metadata has preset recorded
        row = await sqlite_persistence.get_agent(agent_id)
        assert row is not None
        assert row.metadata is not None
        assert row.metadata.preset == "default"
