"""Testing utilities for adgn.

This module provides utilities for testing adgn components, including
environment detection and configuration for different execution contexts.
"""

from adgn.testing.claude_code_web import (
    ClaudeCodeWebEnvironment,
    detect_claude_code_web,
    get_claude_code_web_env,
    get_test_network_mode,
    is_claude_code_web,
)

__all__ = [
    "ClaudeCodeWebEnvironment",
    "detect_claude_code_web",
    "get_claude_code_web_env",
    "get_test_network_mode",
    "is_claude_code_web",
]
