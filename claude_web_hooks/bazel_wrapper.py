#!/usr/bin/env python3
"""Bazel wrapper for Claude Code web - sets proxy env vars and checks health.

Reads configuration from environment variables set by bazelisk_setup.py.
"""

import os
import sys
from pathlib import Path


def require_env(name: str) -> str:
    """Get required environment variable or exit with error."""
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} not set", file=sys.stderr)
        print("Run: python3 -m claude_web_hooks.session_start", file=sys.stderr)
        sys.exit(1)
    return value


REPO_PATH = require_env("DUCKTAPE_REPO_ROOT")
BAZELISK_PATH = require_env("BAZELISK_PATH")
BAZEL_SUPERVISOR_SOCK = require_env("BAZEL_SUPERVISOR_SOCK")
BAZEL_LOCAL_PROXY = require_env("BAZEL_LOCAL_PROXY")


def check_supervisor() -> bool:
    """Check if supervisor socket exists."""
    return Path(BAZEL_SUPERVISOR_SOCK).is_socket()


def check_proxy() -> bool:
    """Check if bazel-proxy service is running under supervisor."""
    try:
        # Import here to avoid dependency at module load time
        from claude_web_hooks.supervisor_setup import is_service_running

        return is_service_running("bazel-proxy")
    except ImportError:
        # Fallback: just check if socket exists
        return check_supervisor()


def print_error(supervisor_running: bool, proxy_running: bool) -> None:
    """Print error message with appropriate instructions."""
    print("✓ supervisord running" if supervisor_running else "✗ supervisord not running", file=sys.stderr)
    print("✓ bazel-proxy running" if proxy_running else "✗ bazel-proxy not running", file=sys.stderr)
    print("", file=sys.stderr)
    print("To start/restart:", file=sys.stderr)
    print(f"  cd {REPO_PATH}", file=sys.stderr)
    print("  python3 -m claude_web_hooks.session_start", file=sys.stderr)
    print("", file=sys.stderr)
    print("Logs: ~/.config/supervisor/bazel-proxy.{log,err.log}", file=sys.stderr)
    print(f"Documentation: {REPO_PATH}/claude_web_hooks/README.md", file=sys.stderr)


def main() -> int:
    """Main entry point."""
    supervisor_running = check_supervisor()
    proxy_running = check_proxy() if supervisor_running else False

    if not supervisor_running or not proxy_running:
        print_error(supervisor_running, proxy_running)
        return 1

    # Set proxy environment variables
    os.environ["HTTPS_PROXY"] = BAZEL_LOCAL_PROXY
    os.environ["HTTP_PROXY"] = BAZEL_LOCAL_PROXY
    os.environ["https_proxy"] = BAZEL_LOCAL_PROXY
    os.environ["http_proxy"] = BAZEL_LOCAL_PROXY

    # Exec bazelisk with remaining arguments
    os.execvp(BAZELISK_PATH, [BAZELISK_PATH] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
