#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up Bazel proxy and git hooks."""

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


def install_git_precommit_hook(project_dir: Path, log: logging.Logger) -> None:
    """Install Bazel-based git pre-commit hook.

    Creates a symlink from .git/hooks/pre-commit to tools/hooks/pre-commit,
    which runs `bazel lint` on staged Python files.
    """
    git_hooks_dir = project_dir / ".git" / "hooks"
    if not git_hooks_dir.exists():
        log.info("Not a git repository (no .git/hooks), skipping git hook install")
        return

    hook_source = project_dir / "tools" / "hooks" / "pre-commit"
    if not hook_source.exists():
        log.warning("Hook source not found: %s", hook_source)
        return

    hook_target = git_hooks_dir / "pre-commit"

    # Calculate relative path from .git/hooks to tools/hooks/pre-commit
    # This is ../../tools/hooks/pre-commit
    relative_source = Path("..") / ".." / "tools" / "hooks" / "pre-commit"

    if hook_target.is_symlink():
        current_target = hook_target.resolve()
        expected_target = hook_source.resolve()
        if current_target == expected_target:
            log.info("Git pre-commit hook already installed")
            return
        # Different symlink target, replace it
        hook_target.unlink()
        log.info("Replacing existing git pre-commit hook symlink")
    elif hook_target.exists():
        # Regular file exists, back it up and replace
        backup = hook_target.with_suffix(".backup")
        hook_target.rename(backup)
        log.info("Backed up existing pre-commit hook to %s", backup)

    hook_target.symlink_to(relative_source)
    log.info("Installed git pre-commit hook: %s -> %s", hook_target, relative_source)


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

    log.info("Environment:\n%s", json.dumps(dict(os.environ), sort_keys=True, indent=2))
    log.info("Setting up dev environment...")

    # Install Bazelisk (downloads correct Bazel version automatically)
    bazelisk_setup.install_bazelisk()

    # Set up Bazel proxy for TLS-inspecting proxy (doesn't need project dir)
    bazel_proxy_setup.setup_bazel_proxy()

    # Project-specific setup (requires CLAUDE_PROJECT_DIR)
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir_str:
        project_dir = Path(project_dir_str)
        log.info("Project: %s", project_dir)

        # Install bazel wrapper that sets proxy env vars
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=project_dir)

        # Install git pre-commit hook that runs bazel lint
        install_git_precommit_hook(project_dir, log)
    else:
        log.warning("CLAUDE_PROJECT_DIR not set, skipping project-specific setup")
        # Still install wrapper without repo-specific config
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=None)

    # Persist PATH modification via CLAUDE_ENV_FILE
    # The bazel wrapper dir needs to be on PATH so `bazel` invokes our wrapper
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
    log.info("  git hook:    installed (bazel lint)")
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
