#!/usr/bin/env python3
"""Bazel wrapper for Claude Code web - sets proxy env vars and checks health.

Reads configuration from environment variables set by bazelisk_setup.py.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_PATH = os.environ.get("DUCKTAPE_REPO_ROOT", "~/code/ducktape")
BAZELISK_PATH = os.environ.get("BAZELISK_PATH", "")
BAZEL_SUPERVISOR_SOCK = os.environ.get("BAZEL_SUPERVISOR_SOCK", "")
BAZEL_SUPERVISOR_CONF = os.environ.get("BAZEL_SUPERVISOR_CONF", "")
BAZEL_LOCAL_PROXY = os.environ.get("BAZEL_LOCAL_PROXY", "")


def check_supervisor() -> bool:
    """Check if supervisor socket exists."""
    if not BAZEL_SUPERVISOR_SOCK:
        return False
    return Path(BAZEL_SUPERVISOR_SOCK).is_socket()


def check_proxy() -> bool:
    """Check if bazel-proxy service is running under supervisor."""
    if not BAZEL_SUPERVISOR_CONF:
        return False
    try:
        result = subprocess.run(
            ["supervisorctl", "-c", BAZEL_SUPERVISOR_CONF, "status", "bazel-proxy"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.returncode == 0 and "RUNNING" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def print_error(supervisor_running: bool, proxy_running: bool) -> None:
    """Print error message with appropriate instructions."""
    print("✓ supervisord running" if supervisor_running else "✗ supervisord not running", file=sys.stderr)
    print("✓ bazel-proxy running" if proxy_running else "✗ bazel-proxy not running", file=sys.stderr)
    print("", file=sys.stderr)

    if not supervisor_running:
        print("To start:", file=sys.stderr)
        print(f"  cd {REPO_PATH}", file=sys.stderr)
        print("  python3 -m claude_web_hooks.session_start", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"Documentation: {REPO_PATH}/claude_web_hooks/README.md", file=sys.stderr)
        print("Setup log: ~/.cache/claude-code-web/session-start.log", file=sys.stderr)
    else:
        print("To start proxy:", file=sys.stderr)
        print(f"  cd {REPO_PATH}", file=sys.stderr)
        print("  python3 -m claude_web_hooks.session_start", file=sys.stderr)
        print("", file=sys.stderr)
        print("Or restart service:", file=sys.stderr)
        print(f"  supervisorctl -c {BAZEL_SUPERVISOR_CONF} start bazel-proxy", file=sys.stderr)
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
