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
    """Install git pre-commit hook using pre-commit framework.

    Runs `pre-commit install` which installs the hook defined in .pre-commit-config.yaml.
    This includes conflict marker detection, syntax checks, and bazel lint.
    """
    import subprocess

    git_dir = project_dir / ".git"
    if not git_dir.exists():
        log.info("Not a git repository (no .git), skipping git hook install")
        return

    precommit_config = project_dir / ".pre-commit-config.yaml"
    if not precommit_config.exists():
        log.warning("No .pre-commit-config.yaml found, skipping git hook install")
        return

    hook_target = git_dir / "hooks" / "pre-commit"
    if hook_target.exists():
        log.info("Git pre-commit hook already installed")
        return

    try:
        result = subprocess.run(
            ["pre-commit", "install"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log.info("Installed git pre-commit hook via pre-commit install")
        else:
            log.warning("pre-commit install failed: %s", result.stderr)
    except FileNotFoundError:
        log.warning("pre-commit not found, skipping git hook install")
    except subprocess.TimeoutExpired:
        log.warning("pre-commit install timed out")


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

    # Detect project directory from CLAUDE_PROJECT_DIR or PWD
    # CLAUDE_PROJECT_DIR should be provided but isn't in Claude Code on the web
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir_str:
        # Fallback: use PWD and verify it's a git repo
        pwd = Path.cwd()
        if (pwd / ".git").exists():
            project_dir_str = str(pwd)
            os.environ["CLAUDE_PROJECT_DIR"] = project_dir_str
            log.info("CLAUDE_PROJECT_DIR not provided, detected from PWD: %s", project_dir_str)
        else:
            log.warning("CLAUDE_PROJECT_DIR not set and PWD is not a git repo, skipping project-specific setup")

    if project_dir_str:
        project_dir = Path(project_dir_str)
        log.info("Project: %s", project_dir)

        # Install bazel wrapper that sets proxy env vars
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=project_dir)

        # Install git pre-commit hook that runs bazel lint
        install_git_precommit_hook(project_dir, log)
    else:
        # No project directory available
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=None)

    # Export debug timestamp to track hook execution
    hook_timestamp = datetime.now().isoformat()
    os.environ["DUCKTAPE_SESSION_START_HOOK_TS"] = hook_timestamp

    # Write timestamp to persistent file for debugging
    timestamp_file = Path.home() / ".ducktape_session_hook_last_run"
    timestamp_file.write_text(f"{hook_timestamp}\n")
    log.info("Session start hook timestamp: %s", hook_timestamp)

    # Persist PATH modification via CLAUDE_ENV_FILE or fallback to symlink
    # The bazel wrapper needs to be on PATH so `bazel` invokes our wrapper
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        env_content = bazelisk_setup.get_env_script()
        # Also export the debug timestamp
        env_content += f'\nexport DUCKTAPE_SESSION_START_HOOK_TS="{hook_timestamp}"\n'
        Path(env_file).write_text(env_content)
        log.info("Wrote PATH update to CLAUDE_ENV_FILE: %s", env_file)
    else:
        # Fallback for Claude Code on the web: symlink to ~/.local/bin
        # Claude Code spawns non-interactive bash which doesn't source rc files
        # but ~/.local/bin is already on PATH
        log.warning("CLAUDE_ENV_FILE not set, using symlink fallback")
        local_bin = Path.home() / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)

        bazel_symlink = local_bin / "bazel"
        bazel_wrapper = bazelisk_setup.WRAPPER_PATH

        if bazel_symlink.exists() or bazel_symlink.is_symlink():
            bazel_symlink.unlink()
        bazel_symlink.symlink_to(bazel_wrapper)
        log.info("Created symlink: %s -> %s", bazel_symlink, bazel_wrapper)

    # Summary
    log.info("=" * 60)
    log.info("Environment ready:")
    log.info("  bazel:       %s", bazelisk_setup.get_status())
    log.info("  Bazel proxy: %s", bazel_proxy_setup.get_status())
    log.info("  git hook:    installed (pre-commit)")
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
