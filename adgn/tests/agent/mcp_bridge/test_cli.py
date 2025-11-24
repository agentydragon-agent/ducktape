"""Test CLI for MCP Bridge - token generation and output formatting."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from hamcrest import assert_that, not_none, has_length, greater_than_or_equal_to, has_item, contains_string

from adgn.agent.mcp_bridge.auth import generate_ui_token
from adgn.agent.mcp_bridge.cli import _run_server

# temp_db fixture is provided by conftest.py


@pytest.fixture
def token_mapping_file(tmp_path: Path) -> Path:
    """Create token mapping file for multi-tenant testing."""
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text(json.dumps({"test-token-1": "agent-1"}), encoding="utf-8")
    return tokens_file


def test_generate_ui_token_creates_random_token(monkeypatch):
    """Test that generate_ui_token creates a secure random token."""
    # Remove env var if present
    monkeypatch.delenv("ADGN_UI_TOKEN", raising=False)

    token1 = generate_ui_token()
    token2 = generate_ui_token()

    # Should be non-empty
    assert_that(token1, not_none())
    assert_that(token2, not_none())

    # Should be different (extremely unlikely to collide)
    assert token1 != token2

    # Should be URL-safe base64 (32 bytes = ~43 characters)
    assert_that(token1, has_length(greater_than_or_equal_to(40)))
    # All characters should be URL-safe base64
    for c in token1:
        assert c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def test_generate_ui_token_respects_env_var(monkeypatch):
    """Test that generate_ui_token uses ADGN_UI_TOKEN if set."""
    test_token = "test-ui-token-from-env"
    monkeypatch.setenv("ADGN_UI_TOKEN", test_token)
    token = generate_ui_token()
    assert token == test_token


@pytest.mark.asyncio
async def test_cli_prints_management_ui_url_with_token(
    temp_db: Path, token_mapping_file: Path, caplog: pytest.LogCaptureFixture
):
    """Test that CLI prints Management UI URL with token parameter in multi-agent mode."""
    # Mock uvicorn.Server to avoid actually starting servers
    mock_server_instance = AsyncMock()
    mock_server_instance.serve = AsyncMock()

    with patch("adgn.agent.mcp_bridge.cli.uvicorn.Server") as mock_server, patch("docker.from_env") as mock_docker:
        mock_server.return_value = mock_server_instance
        mock_docker.return_value = Mock()

        caplog.set_level(logging.INFO)

        # Run server in multi-agent mode (may fail due to mocking, but we just need the logs)
        with contextlib.suppress(Exception):
            await _run_server(
                agent_id=None,
                auth_tokens_path=token_mapping_file,
                db_path=temp_db,
                mcp_config=Mock(mcpServers={}),
                host="127.0.0.1",
                mcp_port=8080,
                ui_port=8081,
                initial_policy=None,
            )

        # Check that logs contain Management UI URL with token
        log_messages = [record.message for record in caplog.records if record.levelname == "INFO"]

        # Find the Management UI log message
        ui_log = [msg for msg in log_messages if "Management UI:" in msg]
        assert ui_log, "Should log Management UI URL"

        # Should contain token parameter
        assert "?token=" in ui_log[0], f"Management UI URL should include token parameter: {ui_log[0]}"

        # Should contain host and port
        assert "127.0.0.1:8081" in ui_log[0], f"Management UI URL should include host and port: {ui_log[0]}"


@pytest.mark.asyncio
async def test_cli_single_agent_mode_no_ui_token(temp_db: Path, caplog: pytest.LogCaptureFixture):
    """Test that single-agent mode doesn't print Management UI URL (no UI in single-agent mode)."""
    # Mock uvicorn.Server to avoid actually starting servers
    mock_server_instance = AsyncMock()
    mock_server_instance.serve = AsyncMock()

    with patch("adgn.agent.mcp_bridge.cli.uvicorn.Server") as mock_server, patch("docker.from_env") as mock_docker:
        mock_server.return_value = mock_server_instance
        mock_docker.return_value = Mock()

        caplog.set_level(logging.INFO)

        # Run server in single-agent mode (may fail due to mocking, but we just need the logs)
        with contextlib.suppress(Exception):
            await _run_server(
                agent_id="test-agent",
                auth_tokens_path=None,
                db_path=temp_db,
                mcp_config=Mock(mcpServers={}),
                host="127.0.0.1",
                mcp_port=8080,
                ui_port=8081,
                initial_policy=None,
            )

        # Check that logs don't contain Management UI URL (single-agent mode has no UI)
        log_messages = [record.message for record in caplog.records if record.levelname == "INFO"]

        # Should not have Management UI log
        ui_logs = [msg for msg in log_messages if "Management UI:" in msg]
        assert not ui_logs, "Single-agent mode should not log Management UI URL"

        # Should have single-agent mode startup message
        assert_that(log_messages, has_item(contains_string("single-agent mode")), "Should log single-agent mode startup")


@pytest.mark.asyncio
async def test_cli_logs_mcp_server_url(temp_db: Path, token_mapping_file: Path, caplog: pytest.LogCaptureFixture):
    """Test that CLI logs MCP server URL in multi-agent mode."""
    # Mock uvicorn.Server to avoid actually starting servers
    mock_server_instance = AsyncMock()
    mock_server_instance.serve = AsyncMock()

    with patch("adgn.agent.mcp_bridge.cli.uvicorn.Server") as mock_server, patch("docker.from_env") as mock_docker:
        mock_server.return_value = mock_server_instance
        mock_docker.return_value = Mock()

        caplog.set_level(logging.INFO)

        # Run server in multi-agent mode (may fail due to mocking, but we just need the logs)
        with contextlib.suppress(Exception):
            await _run_server(
                agent_id=None,
                auth_tokens_path=token_mapping_file,
                db_path=temp_db,
                mcp_config=Mock(mcpServers={}),
                host="127.0.0.1",
                mcp_port=8080,
                ui_port=8081,
                initial_policy=None,
            )

        # Check that logs contain MCP server URL
        log_messages = [record.message for record in caplog.records if record.levelname == "INFO"]

        # Find the MCP server log message
        mcp_log = [msg for msg in log_messages if "MCP server" in msg and "token auth" in msg]
        assert mcp_log, "Should log MCP server URL"

        # Should contain host, port, and /sse path
        assert "127.0.0.1:8080/sse" in mcp_log[0], f"MCP server URL should include host, port, and path: {mcp_log[0]}"
