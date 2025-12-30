#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up Bazel proxy for TLS-inspecting proxies."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
import traceback

from claude_web_hooks import bazel_proxy_setup, bazelisk_setup

CACHE_DIR = Path.home() / ".cache" / "claude-code-web"
LOG_FILE = CACHE_DIR / "session-start.log"


def setup_logging() -> logging.Logger:
    """Configure logging to stdout and file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
    )
    return logging.getLogger(__name__)


def main() -> int:
    log = setup_logging()

    log.info("=" * 60)
    log.info("Hook: %s", __file__)
    log.info("Time: %s", datetime.now().isoformat())
    log.info("Log:  %s", LOG_FILE)
    log.info("=" * 60)

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir_str:
        raise RuntimeError("CLAUDE_PROJECT_DIR not set")
    project_dir = Path(project_dir_str)

    log.info("Project: %s", project_dir)
    log.info("Environment:\n%s", json.dumps(dict(os.environ), sort_keys=True, indent=2))
    log.info("Setting up dev environment...")

    # Install Bazelisk (downloads correct Bazel version automatically)
    bazelisk_setup.install_bazelisk()

    # Set up Bazel proxy for TLS-inspecting proxy
    bazel_proxy_setup.setup_bazel_proxy()

    # Install bazel wrapper that sets proxy env vars
    bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT)

    # Persist PATH modification via CLAUDE_ENV_FILE
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        env_content = bazelisk_setup.get_env_script()
        Path(env_file).write_text(env_content)
        log.info("Wrote PATH update to CLAUDE_ENV_FILE: %s", env_file)
    else:
        log.warning("CLAUDE_ENV_FILE not set, bazel wrapper won't be on PATH")

    # Summary
    log.info("=" * 60)
    log.info("Environment ready:")
    log.info("  bazel:       %s", bazelisk_setup.get_status())
    log.info("  Bazel proxy: %s", bazel_proxy_setup.get_status())
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Can't rely on log here since setup may have failed
        print(f"Hook failed: {e}", file=sys.stderr)
        print(f"Hook: {__file__}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
