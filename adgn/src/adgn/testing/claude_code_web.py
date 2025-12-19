"""Claude Code Web environment detection and configuration.

This module provides utilities for detecting when tests are running inside
the Claude Code Web environment (Anthropic's hosted Claude Code) and
configuring test infrastructure accordingly.

The Claude Code Web environment runs inside a microVM with limited /proc
filesystem emulation, which prevents nested container network namespaces
from working correctly. Tests that don't require network isolation can
use host networking as a workaround.
"""

from __future__ import annotations

import os
from typing import NamedTuple


class ClaudeCodeWebEnvironment(NamedTuple):
    """Information about the Claude Code Web environment."""

    is_claude_code_web: bool
    """True if running inside Claude Code Web (Anthropic's hosted environment)."""

    session_id: str | None
    """The Claude Code session ID if available."""

    container_id: str | None
    """The Claude Code container ID if available."""

    supports_container_network_isolation: bool
    """True if the environment supports nested container network namespaces."""


def detect_claude_code_web() -> ClaudeCodeWebEnvironment:
    """Detect if running in Claude Code Web environment.

    Uses multiple environment variables to reliably detect the environment:
    - CLAUDE_CODE_REMOTE=true: Primary indicator for remote execution
    - CLAUDE_CODE_ENTRYPOINT=remote: Confirms remote entrypoint
    - IS_SANDBOX=yes: Indicates sandbox mode (implies limited /proc)

    Returns:
        ClaudeCodeWebEnvironment with detection results
    """
    is_remote = os.getenv("CLAUDE_CODE_REMOTE") == "true"
    is_remote_entrypoint = os.getenv("CLAUDE_CODE_ENTRYPOINT") == "remote"
    is_sandbox = os.getenv("IS_SANDBOX") == "yes"

    # Claude Code Web is detected when any of these are true
    is_claude_code_web = is_remote or is_remote_entrypoint or is_sandbox

    session_id = os.getenv("CLAUDE_CODE_SESSION_ID") or os.getenv("CLAUDE_CODE_REMOTE_SESSION_ID")
    container_id = os.getenv("CLAUDE_CODE_CONTAINER_ID")

    # Claude Code Web microVM environment doesn't support network namespaces
    # for nested containers due to incomplete /proc filesystem emulation.
    # This affects network modes "none" and "bridge" - only "host" works.
    supports_container_network_isolation = not is_claude_code_web

    return ClaudeCodeWebEnvironment(
        is_claude_code_web=is_claude_code_web,
        session_id=session_id,
        container_id=container_id,
        supports_container_network_isolation=supports_container_network_isolation,
    )


# Cached detection result
_cached_env: ClaudeCodeWebEnvironment | None = None


def get_claude_code_web_env() -> ClaudeCodeWebEnvironment:
    """Get cached Claude Code Web environment info.

    Returns:
        Cached ClaudeCodeWebEnvironment instance
    """
    global _cached_env
    if _cached_env is None:
        _cached_env = detect_claude_code_web()
    return _cached_env


def is_claude_code_web() -> bool:
    """Quick check if running in Claude Code Web environment.

    Returns:
        True if running in Claude Code Web
    """
    return get_claude_code_web_env().is_claude_code_web


def get_test_network_mode(preferred_mode: str = "none") -> str:
    """Get the appropriate network mode for tests.

    In Claude Code Web, network isolation doesn't work, so we fall back
    to host networking for tests that don't strictly require isolation.

    Args:
        preferred_mode: The preferred network mode ("none", "bridge", "host")

    Returns:
        The network mode to use (may be "host" if in Claude Code Web)

    Note:
        Tests that truly require network isolation should use the
        @pytest.mark.requires_network_isolation marker and will be
        skipped when running in Claude Code Web.
    """
    env = get_claude_code_web_env()

    # Allow explicit override via environment variable
    override = os.getenv("ADGN_TEST_NETWORK_MODE")
    if override:
        return override

    # If environment doesn't support network isolation, use host mode
    if not env.supports_container_network_isolation:
        return "host"

    return preferred_mode
