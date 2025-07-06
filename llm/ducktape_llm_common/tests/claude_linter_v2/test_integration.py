"""Integration tests for claude-linter-v2."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


class TestCLIIntegration:
    """Test the full CLI integration."""
    
    def test_pre_hook_bare_except(self):
        """Test that pre-hook blocks bare except."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_bare_except.py",
                "content": """
try:
    x = 1/0
except:
    pass
"""
            },
            "session_id": "test-session-1"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 2  # Exit code for blocked
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "bare except" in response["reason"].lower()
        assert "Line 4:" in response["reason"]
    
    def test_pre_hook_hasattr(self):
        """Test that pre-hook blocks hasattr usage."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_hasattr.py",
                "content": """
obj = object()
if hasattr(obj, 'foo'):
    print("has foo")
"""
            },
            "session_id": "test-session-2"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "hasattr" in response["reason"]
        assert "Line 3:" in response["reason"]
    
    def test_pre_hook_clean_code(self):
        """Test that pre-hook passes clean code."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_clean.py",
                "content": """
def hello():
    try:
        print("Hello, world!")
    except ValueError as e:
        print(f"Error: {e}")
"""
            },
            "session_id": "test-session-3"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["continue"] is True
        assert "decision" not in response or response.get("decision") != "block"
        assert "Pre-commit checks passed" in response["reason"]
    
    @pytest.mark.skipif(
        subprocess.run(["ruff", "--version"], capture_output=True).returncode != 0,
        reason="ruff not available"
    )
    def test_pre_hook_ruff_violation(self):
        """Test that pre-hook blocks ruff violations."""
        request_data = {
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
"""
            },
            "session_id": "test-session-4"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "mutable" in response["reason"].lower()
        assert "Line 6:" in response["reason"]
    
    def test_pre_hook_barrel_init(self):
        """Test that pre-hook blocks barrel __init__.py."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/__init__.py",
                "content": """
from .module1 import *
from .module2 import Class1, Class2

__all__ = ['Class1', 'Class2']
"""
            },
            "session_id": "test-session-5"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "barrel" in response["reason"].lower()
    
    def test_pre_hook_invalid_json(self):
        """Test that pre-hook handles invalid JSON gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input="not valid json",
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 1
        response = json.loads(result.stdout)
        assert "error" in response
        assert "Invalid JSON" in response["error"]
        assert response["continue"] is False
    
    def test_pre_hook_non_python_file(self):
        """Test that pre-hook passes non-Python files."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test.txt",
                "content": "This is just a text file with except: and hasattr"
            },
            "session_id": "test-session-6"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "pre"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["continue"] is True
        assert "Pre-commit checks passed" in response["reason"]
    
    def test_post_hook_basic(self):
        """Test that post-hook runs without errors."""
        request_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/test_post.py",
                "content": "x=1+2  # poorly formatted"
            },
            "session_id": "test-session-7"
        }
        
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "hook", "--type", "post"],
            input=json.dumps(request_data),
            capture_output=True,
            text=True
        )
        
        # Post-hook returns exit code 2 when showing FYI messages
        assert result.returncode in (0, 2)
        response = json.loads(result.stdout)
        assert response["continue"] is True
        # FYI messages use decision=block but with "FYI:" prefix
        if response.get("decision") == "block":
            assert "FYI:" in response["reason"]


class TestSessionCommands:
    """Test session management commands."""
    
    def test_session_list(self):
        """Test listing sessions."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli", "session", "list"],
            capture_output=True,
            text=True,
            cwd="/tmp"  # Use a specific directory
        )
        
        assert result.returncode == 0
        # Output should be valid (might be empty if no sessions)
        assert "Sessions in" in result.stdout or "No sessions found" in result.stdout
    
    def test_session_allow(self):
        """Test adding an allow rule."""
        result = subprocess.run(
            [
                sys.executable, "-m", "ducktape_llm_common.claude_linter_v2.cli",
                "session", "allow", "Edit('**/*.py')"
            ],
            capture_output=True,
            text=True,
            cwd="/tmp"
        )
        
        assert result.returncode == 0
        # Check for the actual output format
        assert "Permission granted" in result.stdout or "Added allow rule" in result.stdout