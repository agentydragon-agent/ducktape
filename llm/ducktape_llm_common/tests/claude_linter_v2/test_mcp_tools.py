"""Unit tests for MCP tool handling in claude-linter-v2."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducktape_llm_common.claude_code_api import PostToolUseRequest, PreToolUseRequest
from ducktape_llm_common.claude_linter_v2.config.clean_models import ModularConfig
from ducktape_llm_common.claude_linter_v2.config.models import AutofixCategory, PostToolHookConfig
from ducktape_llm_common.claude_linter_v2.hooks.handler import HookHandler
from ducktape_llm_common.claude_outcomes import PostToolSuccess, PreToolApprove


class TestMCPTools:
    """Test MCP tool handling in hooks."""

    @pytest.fixture
    def handler(self):
        """Create a handler instance."""
        return HookHandler()

    def test_mcp_tool_with_extra_fields(self, handler, session_id):
        """Test that MCP tools with custom fields are handled correctly."""
        # Create a request with MCP-specific fields
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_memory_search_nodes",
            tool_input={
                # Standard fields
                "file_path": None,
                "content": None,
                # MCP-specific fields (should be allowed by extra="allow")
                "query": "authentication patterns",
                "limit": 5,
                "server": "memory",
            },
        )

        # Should approve since it's not a file operation
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_mcp_puppeteer_tool(self, handler, session_id):
        """Test MCP puppeteer tool with its specific parameters."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_puppeteer_navigate",
            tool_input={"url": "https://example.com", "allowDangerous": True, "wait_for": "networkidle2"},
            tool_result={"success": True, "screenshot": "base64_data_here"},
        )

        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    def test_mcp_filesystem_tool_with_path(self, handler, session_id, monkeypatch):
        """Test MCP filesystem tool that should trigger path checks."""
        # Create a minimal mock config that properly mocks the nested structure
        mock_config = MagicMock()
        mock_config.access_control = []
        mock_config.repo_rules = []
        mock_config.hooks = {"post": MagicMock(auto_fix=False, inject_permissions=False)}
        mock_config.python.hard_blocks.bare_except = True
        mock_config.python.hard_blocks.getattr_setattr = True
        mock_config.python.hard_blocks.barrel_init = True
        mock_config.python.ruff_force_select = []
        mock_config.max_errors_to_show = 3

        # Mock the config at instance level (restored automatically by monkeypatch)
        monkeypatch.setattr(handler.config_loader, "_config", mock_config)

        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_filesystem_write_file",
            tool_input={"path": "/tmp/test.txt", "content": "Hello, world!"},
        )

        # Should check access control even for MCP tools
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_unknown_mcp_tool_fields(self, handler, session_id):
        """Test that unknown MCP tool fields don't cause errors."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_custom_tool",
            tool_input={
                # Completely custom fields
                "custom_field_1": "value1",
                "nested_config": {"key": "value"},
                "array_param": [1, 2, 3],
                "boolean_flag": True,
            },
        )

        # Should not raise any validation errors
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_mcp_tool_with_python_file(self, handler, session_id):
        """Test MCP tool operating on Python files - MCP tools are NOT checked for Python violations."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_editor_open",
            tool_input={
                "file_path": Path("/home/user/test.py"),
                "content": "try:\n    pass\nexcept:\n    pass",  # Bare except
            },
        )

        # MCP tools are not checked for Python violations - only known tool types are
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_mcp_tool_post_hook_with_autofix(self, handler, session_id, tmp_path):
        """Test MCP tool in post-hook with autofix enabled."""

        # Create a real config model with proper nested structure
        config = ModularConfig()
        config.hooks["post"] = PostToolHookConfig(auto_fix=True, autofix_categories=[AutofixCategory.FORMATTING])

        # Replace the config loader's config
        handler.config_loader._config = config

        # Create a real Python file
        test_file = tmp_path / "test.py"
        test_file.write_text("import os\nimport sys\n\n\ndef test():\n    pass")

        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_editor_save",
            tool_input={"file_path": test_file, "content": "import os\nimport sys\n\n\ndef test():\n    pass"},
            tool_result={"saved": True},
        )

        outcome = handler._handle_post_hook(request, session_id)

        # Should succeed since no violations
        assert isinstance(outcome, PostToolSuccess)

    def test_mcp_tool_name_variations(self, handler, session_id):
        """Test various MCP tool naming conventions."""
        tool_names = [
            "mcp__memory__search_nodes",  # Double underscore
            "mcp_memory_search",  # Single underscore
            "mcp-memory-search",  # Hyphen
            "mcpMemorySearch",  # CamelCase
            "MCP_MEMORY_SEARCH",  # Upper case
        ]

        for tool_name in tool_names:
            request = PreToolUseRequest(
                session_id=session_id, hook_event_name="PreToolUse", tool_name=tool_name, tool_input={"query": "test"}
            )

            # All should be handled without errors
            outcome = handler._handle_pre_hook(request, session_id)
            assert isinstance(outcome, PreToolApprove)

    def test_mcp_tool_with_complex_result(self, handler, session_id):
        """Test MCP tool with complex nested result structure."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_knowledge_graph_query",
            tool_input={"query": "MATCH (n:Node) RETURN n LIMIT 10", "database": "neo4j"},
            tool_result={
                "nodes": [
                    {
                        "id": 1,
                        "labels": ["Person", "Developer"],
                        "properties": {"name": "Alice", "skills": ["Python", "JavaScript"]},
                    }
                ],
                "relationships": [],
                "metadata": {"query_time_ms": 42, "node_count": 1},
            },
        )

        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    def test_mcp_tool_error_result(self, handler, session_id):
        """Test MCP tool that returned an error."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_api_call",
            tool_input={"endpoint": "/api/users", "method": "GET"},
            tool_result={"error": "Connection timeout", "status_code": None, "success": False},
        )

        # Should still process normally - hooks don't care about tool success
        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    @pytest.mark.parametrize(
        ("tool_name", "input_fields", "should_check_python"),
        [
            # MCP tools - never checked for Python (only WriteToolCall is)
            ("mcp_memory_create", {"name": "test", "content": "data"}, False),
            ("mcp_browser_click", {"selector": "#button"}, False),
            ("mcp_fs_write", {"file_path": "test.py", "content": "print('hi')"}, False),
            ("mcp_editor_format", {"file_path": "app.py", "content": "x=1"}, False),
            ("mcp_tool", {"file_path": "test.js", "content": "console.log()"}, False),
            ("mcp_tool", {"file_path": None, "content": "print('hi')"}, False),
        ],
    )
    def test_mcp_tool_python_detection(self, handler, session_id, tool_name, input_fields, should_check_python):
        """Test that MCP tools are never detected as Python files (only WriteToolCall is checked)."""
        tool_input_dict = {"file_path": None, "content": None, **input_fields}

        request = PreToolUseRequest(
            session_id=session_id, hook_event_name="PreToolUse", tool_name=tool_name, tool_input=dict(**tool_input_dict)
        )

        # MCP tools are never checked for Python - only WriteToolCall is
        is_python = handler._is_python_file(request)
        assert is_python == should_check_python

    def test_mcp_tool_session_tracking(self, handler, session_id):
        """Test that MCP tools properly track sessions."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_workspace_list",
            tool_input={"directory": "/home/user/project"},
        )

        # Process request via handle() which triggers session tracking
        handler.handle("PreToolUse", request)

        # Verify the session was tracked by checking the session file exists
        session_file = handler.session_manager._session_file(session_id)
        assert session_file.exists(), f"Session file was not created at {session_file}"

        # Also verify we can load the session data
        session_data = handler.session_manager._load_session(session_id)
        assert session_data.id == session_id
        assert session_data.last_seen is not None

    def test_mcp_tool_with_file_path_does_not_update_working_dir(self, handler, session_id):
        """Test that MCP tools do NOT update the working directory (only FilePathToolCall types do)."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_file_manager_open",
            tool_input={"file_path": Path("/home/user/projects/myapp/src/main.py"), "content": "# Main file"},
        )

        with patch.object(handler.session_manager, "track_session") as mock_track:
            handler._track_session(request, session_id)

            # MCP tools do NOT update working dir - only known FilePathToolCall types do
            # So it should use cwd instead
            mock_track.assert_called_once()
            call_args = mock_track.call_args[0]
            assert call_args[0] == session_id
            # Working dir should be cwd, not the file's parent
            assert call_args[1] == Path.cwd()


class TestMCPToolsUnexpectedFormats:
    """Test MCP tools with completely unexpected/arbitrary formats."""

    @pytest.fixture
    def handler(self):
        """Create a handler instance."""
        return HookHandler()

    def test_stock_price_tool(self, handler, session_id):
        """Test a financial MCP tool with custom format."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_finance_get_stock_price",
            tool_input={
                "symbol": "AAPL",
                "date": "2024-01-15",
                "exchange": "NASDAQ",
                "include_extended_hours": True,
                "currency": "USD",
            },
        )

        # Should not crash
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_weather_tool_nested_structure(self, handler, session_id):
        """Test weather tool with deeply nested structure."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_weather_forecast",
            tool_input={
                "location": {"type": "coordinates", "lat": 37.7749, "lon": -122.4194, "name": "San Francisco"},
                "forecast_days": 7,
                "units": "metric",
                "include_alerts": True,
            },
            tool_result={
                "current": {"temp": 18.5, "feels_like": 17.2, "conditions": "Partly cloudy"},
                "forecast": [
                    {"date": "2024-01-16", "high": 20, "low": 12},
                    {"date": "2024-01-17", "high": 19, "low": 11},
                ],
            },
        )

        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    def test_ai_model_tool_with_arrays(self, handler, session_id):
        """Test AI/ML tool with array parameters."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_ml_predict",
            tool_input={
                "model_id": "sentiment-v2",
                "inputs": ["I love this!", "This is terrible", "Not sure about this"],
                "parameters": {"temperature": 0.7, "max_tokens": 100, "top_p": 0.9},
                "return_probabilities": True,
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_database_tool_with_sql(self, handler, session_id):
        """Test database tool with SQL that might trigger security checks."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_postgres_query",
            tool_input={
                "connection_string": "postgresql://user:pass@localhost/db",
                "query": "SELECT * FROM users WHERE id = $1",
                "params": [123],
                "timeout_ms": 5000,
                "return_format": "json",
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_iot_device_control(self, handler, session_id):
        """Test IoT device control with mixed types."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_smart_home_control",
            tool_input={
                "device_id": "light.living_room",
                "action": "set_state",
                "payload": {
                    "on": True,
                    "brightness": 75,
                    "color": {"r": 255, "g": 200, "b": 100},
                    "transition_time": 2.5,
                },
                "confirm": True,
            },
            tool_result={"success": True, "device_state": {"on": True, "brightness": 75}},
        )

        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    def test_blockchain_tool_with_hex_data(self, handler, session_id):
        """Test blockchain tool with hex strings and addresses."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_ethereum_send_transaction",
            tool_input={
                "from_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f4a7e4",
                "to_address": "0x5aAeb6053f3E94C9b9A09f33669435E7Ef1BeAed",
                "value_wei": "1000000000000000000",  # 1 ETH
                "gas_limit": 21000,
                "gas_price_gwei": "30",
                "nonce": 42,
                "data": "0x",
                "chain_id": 1,
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_calendar_tool_with_datetime(self, handler, session_id):
        """Test calendar tool with various datetime formats."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_calendar_create_event",
            tool_input={
                "title": "Team Meeting",
                "start": "2024-01-20T14:00:00Z",
                "end": "2024-01-20T15:30:00Z",
                "timezone": "America/New_York",
                "attendees": ["alice@example.com", "bob@example.com"],
                "recurrence": {"freq": "WEEKLY", "count": 10, "byday": ["MO", "WE", "FR"]},
                "reminder_minutes": [15, 60],
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_image_processing_tool(self, handler, session_id):
        """Test image processing tool with base64 data."""
        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_image_resize",
            tool_input={
                "image_data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
                "width": 100,
                "height": 100,
                "maintain_aspect_ratio": True,
                "format": "webp",
                "quality": 85,
            },
            tool_result={
                "success": True,
                "output_size_bytes": 2048,
                "output_dimensions": {"width": 100, "height": 100},
            },
        )

        outcome = handler._handle_post_hook(request, session_id)
        assert isinstance(outcome, PostToolSuccess)

    def test_scientific_computation_tool(self, handler, session_id):
        """Test scientific computation tool with complex numeric data."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_scipy_optimize",
            tool_input={
                "function": "minimize",
                "objective": "x**2 + y**2",
                "variables": ["x", "y"],
                "initial_guess": [1.0, 1.0],
                "method": "BFGS",
                "constraints": [{"type": "ineq", "fun": "x + y - 1"}, {"type": "eq", "fun": "x - 2*y"}],
                "bounds": [(-10, 10), (-10, 10)],
                "options": {"maxiter": 1000, "ftol": 1e-9},
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_completely_unknown_format(self, handler, session_id):
        """Test with completely made-up tool and format."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_quantum_entangle_qubits",
            tool_input={
                "qubit_ids": ["q0", "q1", "q2"],
                "entanglement_type": "GHZ",
                "measurement_basis": "computational",
                "shots": 1024,
                "backend": "simulator",
                "noise_model": {"depolarizing": 0.01, "readout_error": [[0.97, 0.03], [0.02, 0.98]]},
                "optimization_level": 3,
                "seed": 42,
            },
        )

        # Should handle gracefully without crashing
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_empty_tool_input(self, handler, session_id):
        """Test MCP tool with no input parameters."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_system_get_time",
            tool_input={},  # No fields at all
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_tool_with_none_values(self, handler, session_id):
        """Test tool with None values in various fields."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_data_processor",
            tool_input={
                "required_field": "value",
                "optional_field": None,
                "nested_object": {"key1": "value1", "key2": None, "key3": {"nested": None}},
                "array_with_nulls": [1, None, 3, None, 5],
                "completely_null": None,
            },
        )

        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)

    def test_tool_with_special_characters(self, handler, session_id):
        """Test tool with special characters in field names."""
        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp-weird.tool$name",
            tool_input=dict(
                **{
                    "field-with-hyphens": "value",
                    "field.with.dots": "value",
                    "field$with$dollars": "value",
                    "field@with@at": "value",
                    "field with spaces": "value",
                    "field_with_underscores": "value",
                    "fieldWithCamelCase": "value",
                    "FIELD_WITH_CAPS": "value",
                    "123_numeric_start": "value",
                    "field:with:colons": "value",
                }
            ),
        )

        # Should not crash on weird field names
        outcome = handler._handle_pre_hook(request, session_id)
        assert isinstance(outcome, PreToolApprove)


class TestMCPToolLogging:
    """Test logging behavior for MCP tools."""

    @pytest.fixture
    def handler(self):
        """Create a handler with mocked logging."""
        handler = HookHandler()
        # Ensure log directory exists
        handler.log_dir.mkdir(parents=True, exist_ok=True)
        return handler

    def test_mcp_tool_logging(self, handler, session_id, tmp_path):
        """Test that MCP tool calls are properly logged."""
        # Override log directory
        handler.log_dir = tmp_path

        request = PostToolUseRequest(
            session_id=session_id,
            hook_event_name="PostToolUse",
            tool_name="mcp_analytics_track",
            tool_input={
                "event": "user_action",
                "properties": {"action": "click", "target": "button"},
                "timestamp": datetime.now().isoformat(),
            },
            tool_result={"tracked": True},
        )

        # Process request
        handler._handle_post_hook(request, session_id)

        # Check log file was created
        log_file = tmp_path / f"{session_id}.log"
        assert log_file.exists()

        # Read and verify log content
        with log_file.open() as f:
            lines = f.readlines()

        # Should have decision logs and final log
        assert len(lines) >= 1

        # Parse the main log entry
        for line in lines:
            if line.startswith('{"timestamp"'):
                log_data = json.loads(line)
                assert log_data["hook_type"] == "PostToolUse"
                assert log_data["request"]["data"]["tool_name"] == "mcp_analytics_track"
                assert "event" in log_data["request"]["data"]["tool_input"]
                break

    def test_mcp_tool_decision_logging(self, handler, session_id, tmp_path):
        """Test that decision points are logged for MCP tools."""
        handler.log_dir = tmp_path

        request = PreToolUseRequest(
            session_id=session_id,
            hook_event_name="PreToolUse",
            tool_name="mcp_database_query",
            tool_input={"query": "SELECT * FROM users", "database": "postgres"},
        )

        # Process request
        handler._handle_pre_hook(request, session_id)

        # Read log file
        log_file = tmp_path / f"{session_id}.log"
        with log_file.open() as f:
            content = f.read()

        # Should have logged decision points
        assert "DECISION:" in content
        assert "pre_hook_start" in content
        assert "access_control" in content
        assert "file_type_check" in content
