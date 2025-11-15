"""Integration tests for claude-linter-v2."""

import json
import subprocess
import sys

import pytest


class TestCLIIntegration:
    """Test the full CLI integration."""

    def test_pre_hook_bare_except(self):
        """Test that pre-hook blocks bare except."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_bare_except.py",
                "content": """
try:
    x = 1/0
except:
    pass
""",
            },
            "session_id": "12345678-1234-5678-1234-567812345678",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0  # CLI always exits 0, check JSON response
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "bare except" in response["reason"].lower()
        assert "Line 4:" in response["reason"]

    def test_pre_hook_hasattr(self):
        """Test that pre-hook blocks hasattr usage."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_hasattr.py",
                "content": """
obj = object()
if hasattr(obj, 'foo'):
    print("has foo")
""",
            },
            "session_id": "12345678-1234-5678-1234-567812345679",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "hasattr" in response["reason"]
        assert "Line 3:" in response["reason"]

    def test_pre_hook_clean_code(self):
        """Test that pre-hook passes clean code."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_clean.py",
                "content": """
def hello():
    try:
        print("Hello, world!")
    except ValueError as e:
        print(f"Error: {e}")
""",
            },
            "session_id": "12345678-1234-5678-1234-567812345680",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["continue"] is True
        # Clean code just returns {"continue": true}
        assert "decision" not in response or response.get("decision") != "block"

    @pytest.mark.skipif(
        subprocess.run(["ruff", "--version"], capture_output=True, check=False).returncode != 0,
        reason="ruff not available",
    )
    def test_pre_hook_ruff_violation(self):
        """Test that pre-hook blocks ruff violations."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_mutable_default.py",
                "content": """
import os

def get_data():
    # Mutable default argument
    def process(items=[]):
        items.append(1)
        return items
""",
            },
            "session_id": "12345678-1234-5678-1234-567812345681",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "mutable" in response["reason"].lower()
        assert "Line 6:" in response["reason"]

    def test_pre_hook_barrel_init(self):
        """Test that pre-hook blocks barrel __init__.py."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/__init__.py",
                "content": """
from .module1 import *
from .module2 import Class1, Class2

__all__ = ['Class1', 'Class2']
""",
            },
            "session_id": "12345678-1234-5678-1234-567812345682",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "barrel" in response["reason"].lower()

    def test_pre_hook_invalid_json(self):
        """Test that pre-hook handles invalid JSON gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input="not valid json",
            capture_output=True,
            text=True,
            check=False,
        )

        # Invalid JSON should crash the CLI
        assert result.returncode != 0
        # When CLI crashes, there's no JSON output
        assert "JSON parse error" in result.stderr or "Invalid JSON" in result.stderr

    def test_pre_hook_non_python_file(self):
        """Test that pre-hook passes non-Python files."""
        request_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test.txt",
                "content": "This is just a text file with except: and hasattr",
            },
            "session_id": "12345678-1234-5678-1234-567812345683",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["continue"] is True
        # Non-Python files just return {"continue": true}

    def test_post_hook_basic(self):
        """Test that post-hook runs without errors."""
        request_data = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test_post.py", "content": "x=1+2  # poorly formatted"},
            "session_id": "12345678-1234-5678-1234-567812345684",
        }

        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True,
            check=False,
        )

        # CLI always exits 0
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["continue"] is True
        # Post-hook may apply autofix and notify Claude
        if response.get("decision") == "block":
            assert "Autofix:" in response["reason"] or "Violations:" in response["reason"]


class TestSessionCommands:
    """Test session management commands."""

    def test_session_list(self):
        """Test listing sessions."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "session", "list"],
            capture_output=True,
            text=True,
            cwd="/tmp",
            check=False,  # Use a specific directory
        )

        assert result.returncode == 0
        # Output should be valid (might be empty if no sessions)
        assert "Sessions in" in result.stdout or "No sessions found" in result.stdout

    def test_session_allow(self):
        """Test adding an allow rule."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "session", "allow", "Edit('**/*.py')"],
            capture_output=True,
            text=True,
            cwd="/tmp",
            check=False,
        )

        assert result.returncode == 0
        # Check for the actual output format
        assert "Permission granted" in result.stdout or "Added allow rule" in result.stdout
