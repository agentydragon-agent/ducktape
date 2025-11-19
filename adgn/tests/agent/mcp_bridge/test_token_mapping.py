"""Test TokenMapping with role-based token format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adgn.agent.mcp_bridge.auth import TokenInfo, TokenMapping, TokenRole
from adgn.agent.types import AgentID


def test_token_mapping_new_format_agent(tmp_path: Path):
    """Test TokenMapping with new format for AGENT role."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "agent-token-123": {"role": "agent", "agent_id": "chatgpt-agent"},
        "agent-token-456": {"role": "agent", "agent_id": "claude-agent"},
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Test first token
    info1 = mapping.get_token_info("agent-token-123")
    assert info1 is not None
    assert info1.role == TokenRole.AGENT
    assert info1.agent_id == AgentID("chatgpt-agent")

    # Test second token
    info2 = mapping.get_token_info("agent-token-456")
    assert info2 is not None
    assert info2.role == TokenRole.AGENT
    assert info2.agent_id == AgentID("claude-agent")

    # Test unknown token
    info3 = mapping.get_token_info("unknown-token")
    assert info3 is None


def test_token_mapping_new_format_human(tmp_path: Path):
    """Test TokenMapping with new format for HUMAN role."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "ui-token-789": {"role": "human"},
        "admin-token-101": {"role": "human"},
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Test first token
    info1 = mapping.get_token_info("ui-token-789")
    assert info1 is not None
    assert info1.role == TokenRole.HUMAN
    assert info1.agent_id is None

    # Test second token
    info2 = mapping.get_token_info("admin-token-101")
    assert info2 is not None
    assert info2.role == TokenRole.HUMAN
    assert info2.agent_id is None


def test_token_mapping_mixed_roles(tmp_path: Path):
    """Test TokenMapping with mixed HUMAN and AGENT tokens."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "agent-token-123": {"role": "agent", "agent_id": "chatgpt-agent"},
        "ui-token-789": {"role": "human"},
        "agent-token-456": {"role": "agent", "agent_id": "claude-agent"},
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Test AGENT tokens
    agent_info1 = mapping.get_token_info("agent-token-123")
    assert agent_info1 is not None
    assert agent_info1.role == TokenRole.AGENT
    assert agent_info1.agent_id == AgentID("chatgpt-agent")

    agent_info2 = mapping.get_token_info("agent-token-456")
    assert agent_info2 is not None
    assert agent_info2.role == TokenRole.AGENT
    assert agent_info2.agent_id == AgentID("claude-agent")

    # Test HUMAN token
    human_info = mapping.get_token_info("ui-token-789")
    assert human_info is not None
    assert human_info.role == TokenRole.HUMAN
    assert human_info.agent_id is None


def test_token_mapping_legacy_format(tmp_path: Path):
    """Test TokenMapping with legacy format (backwards compatibility)."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "legacy-token-123": "chatgpt-agent",
        "legacy-token-456": "claude-agent",
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Legacy format should default to AGENT role
    info1 = mapping.get_token_info("legacy-token-123")
    assert info1 is not None
    assert info1.role == TokenRole.AGENT
    assert info1.agent_id == AgentID("chatgpt-agent")

    info2 = mapping.get_token_info("legacy-token-456")
    assert info2 is not None
    assert info2.role == TokenRole.AGENT
    assert info2.agent_id == AgentID("claude-agent")

    # Test legacy get_agent_id method
    assert mapping.get_agent_id("legacy-token-123") == AgentID("chatgpt-agent")
    assert mapping.get_agent_id("legacy-token-456") == AgentID("claude-agent")


def test_token_mapping_mixed_legacy_and_new(tmp_path: Path):
    """Test TokenMapping with mix of legacy and new formats."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "legacy-token-123": "chatgpt-agent",  # Legacy format
        "new-agent-token": {"role": "agent", "agent_id": "claude-agent"},  # New format
        "ui-token": {"role": "human"},  # New format
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Legacy format token
    legacy_info = mapping.get_token_info("legacy-token-123")
    assert legacy_info is not None
    assert legacy_info.role == TokenRole.AGENT
    assert legacy_info.agent_id == AgentID("chatgpt-agent")

    # New format AGENT token
    agent_info = mapping.get_token_info("new-agent-token")
    assert agent_info is not None
    assert agent_info.role == TokenRole.AGENT
    assert agent_info.agent_id == AgentID("claude-agent")

    # New format HUMAN token
    human_info = mapping.get_token_info("ui-token")
    assert human_info is not None
    assert human_info.role == TokenRole.HUMAN
    assert human_info.agent_id is None


def test_token_mapping_agent_missing_agent_id(tmp_path: Path):
    """Test that AGENT role without agent_id raises error."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "bad-agent-token": {"role": "agent"},  # Missing agent_id
    }
    token_file.write_text(json.dumps(tokens))

    with pytest.raises(ValueError, match="AGENT role token .* missing agent_id"):
        TokenMapping(token_file)


def test_token_mapping_invalid_token_value(tmp_path: Path):
    """Test that invalid token value raises error."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "bad-token": 12345,  # Neither string nor dict
    }
    token_file.write_text(json.dumps(tokens))

    with pytest.raises(ValueError, match="Invalid token mapping value"):
        TokenMapping(token_file)


def test_token_mapping_invalid_json(tmp_path: Path):
    """Test that invalid JSON raises error."""
    token_file = tmp_path / "tokens.json"
    token_file.write_text("not valid json")

    with pytest.raises(json.JSONDecodeError):
        TokenMapping(token_file)


def test_token_mapping_non_dict(tmp_path: Path):
    """Test that non-dict JSON raises error."""
    token_file = tmp_path / "tokens.json"
    token_file.write_text('["array", "not", "dict"]')

    with pytest.raises(ValueError, match="Token mapping must be a JSON object"):
        TokenMapping(token_file)


def test_token_mapping_file_not_found(tmp_path: Path):
    """Test that missing file raises FileNotFoundError."""
    non_existent_file = tmp_path / "does-not-exist.json"

    with pytest.raises(FileNotFoundError, match="Token mapping file not found"):
        TokenMapping(non_existent_file)


def test_token_mapping_get_agent_id_legacy_method(tmp_path: Path):
    """Test legacy get_agent_id method returns None for HUMAN tokens."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "agent-token": {"role": "agent", "agent_id": "some-agent"},
        "human-token": {"role": "human"},
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # get_agent_id should return agent_id for AGENT tokens
    assert mapping.get_agent_id("agent-token") == AgentID("some-agent")

    # get_agent_id should return None for HUMAN tokens
    assert mapping.get_agent_id("human-token") is None

    # get_agent_id should return None for unknown tokens
    assert mapping.get_agent_id("unknown-token") is None


def test_token_mapping_reload(tmp_path: Path):
    """Test that reload() updates the mapping."""
    token_file = tmp_path / "tokens.json"
    tokens = {
        "token-1": {"role": "agent", "agent_id": "agent-1"},
    }
    token_file.write_text(json.dumps(tokens))

    mapping = TokenMapping(token_file)

    # Initial state
    assert mapping.get_token_info("token-1") is not None
    assert mapping.get_token_info("token-2") is None

    # Update file
    tokens["token-2"] = {"role": "human"}
    token_file.write_text(json.dumps(tokens))

    # Reload
    mapping.reload()

    # Verify updated state
    assert mapping.get_token_info("token-1") is not None
    assert mapping.get_token_info("token-2") is not None
    assert mapping.get_token_info("token-2").role == TokenRole.HUMAN
