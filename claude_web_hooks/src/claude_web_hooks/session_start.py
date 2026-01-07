#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up Bazel proxy and git hooks."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from claude_web_hooks import bazel_proxy_setup, bazelisk_setup

CACHE_DIR = Path.home() / ".cache" / "claude-code-web"
LOG_FILE = CACHE_DIR / "session-start.log"


def emit_session_context(log: logging.Logger, had_warnings: bool, had_errors: bool) -> None:
    """Emit structured context summary for Claude Code to inject into transcript.

    This output goes to stdout and gets injected as context for the operating agent.
    """
    print("\n" + "=" * 60)
    print("SESSION START HOOK SUMMARY")
    print("=" * 60)

    # Tell the LLM about the Claude Code on the web environment
    print("\nYou are running in Claude Code on the web (gVisor sandbox container).")
    print("This environment has specific constraints and workarounds documented in skills.")
    print("\nAvailable skills for this environment:")
    print("  - github-actions-web: Run GitHub Actions locally with act + podman")
    print("    Use this skill when you need to test CI workflows in this container.")

    if had_errors:
        print("\n[ERROR] Session start completed with ERRORS - some features may not work correctly")
        print(f"[ERROR] Check log file for details: {LOG_FILE}")
    elif had_warnings:
        print("\n[WARNING] Session start completed with warnings - using fallback configurations")
        print(f"Review log file for details: {LOG_FILE}")
    else:
        print("\nSession start completed successfully - all features configured")

    print(f"\nFull log available at: {LOG_FILE}")
    print("=" * 60 + "\n")
    sys.stdout.flush()


def install_git_precommit_hook(project_dir: Path, log: logging.Logger) -> None:
    """Install git pre-commit hook using pre-commit framework.

    First ensures pre-commit is installed via pip, then runs `pre-commit install`
    which installs the hook defined in .pre-commit-config.yaml.
    This includes conflict marker detection, syntax checks, and bazel lint.
    """
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

    # Ensure pre-commit is installed (version from .pre-commit-config.yaml comment)
    try:
        subprocess.run(["pre-commit", "--version"], capture_output=True, check=True, timeout=5)
        log.info("pre-commit already available")
    except (FileNotFoundError, subprocess.CalledProcessError):
        log.info("Installing pre-commit==4.0.1 via pip")
        try:
            result = subprocess.run(
                ["pip", "install", "--user", "pre-commit==4.0.1"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                log.warning("Failed to install pre-commit: %s", result.stderr)
                return
            log.info("pre-commit installed successfully")
        except subprocess.TimeoutExpired:
            log.warning("pre-commit installation timed out")
            return

    # Install the git hook
    try:
        result = subprocess.run(
            ["pre-commit", "install"], check=False, cwd=project_dir, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log.info("Installed git pre-commit hook via pre-commit install")
        else:
            log.warning("pre-commit install failed: %s", result.stderr)
    except FileNotFoundError:
        log.warning("pre-commit not found after installation attempt")
    except subprocess.TimeoutExpired:
        log.warning("pre-commit install timed out")


class LogLevelCounter(logging.Handler):
    """Handler that counts warnings and errors."""

    def __init__(self):
        super().__init__()
        self.warning_count = 0
        self.error_count = 0

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.warning_count += 1
        elif record.levelno >= logging.ERROR:
            self.error_count += 1


def setup_logging() -> tuple[logging.Logger, LogLevelCounter]:
    """Configure logging to stdout and file with clear log level indicators.

    Returns logger and a counter to track warnings/errors.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Format with clear log level indicators
    # INFO is unmarked (normal), WARNING/ERROR are clearly marked
    class LogLevelFormatter(logging.Formatter):
        def format(self, record):
            if record.levelno == logging.INFO:
                # INFO logs don't need a prefix - they're expected
                return record.getMessage()
            if record.levelno == logging.WARNING:
                return f"[WARNING] {record.getMessage()}"
            if record.levelno == logging.ERROR:
                return f"[ERROR] {record.getMessage()}"
            # Any other level is unexpected - highlight it
            return f"[{record.levelname}] {record.getMessage()}"

    formatter = LogLevelFormatter()

    # Stdout handler for context injection
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    # File handler for persistence
    file_handler = logging.FileHandler(LOG_FILE, mode="a")
    file_handler.setFormatter(formatter)

    # Counter handler to track warnings/errors
    counter = LogLevelCounter()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(stdout_handler)
    logger.addHandler(file_handler)
    logger.addHandler(counter)

    return logger, counter


def main() -> int:
    log, counter = setup_logging()

    log.info("=" * 60)
    log.info("Hook: %s", __file__)
    log.info("Time: %s", datetime.now().isoformat())
    log.info("Log:  %s", LOG_FILE)
    log.info("=" * 60)

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        emit_session_context(log, had_warnings=False, had_errors=False)
        return 0

    log.info("Environment:\n%s", json.dumps(dict(os.environ), sort_keys=True, indent=2))
    log.info("Setting up dev environment...")

    # Detect project directory FIRST so it's available for bazel proxy setup
    # (needed for local registry configuration with native ELF ape binaries)
    # Documentation states CLAUDE_PROJECT_DIR should be provided when Claude Code spawns hooks,
    # but it's not available in Claude Code on the web as of 2.0.59
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir_str:
        log.info("CLAUDE_PROJECT_DIR provided: %s", project_dir_str)
    else:
        log.warning("CLAUDE_PROJECT_DIR not provided by Claude Code (expected per docs, missing in web v2.0.59)")
        # Fallback: use PWD and verify it's a git repo
        pwd = Path.cwd()
        log.info("Attempting fallback: checking if PWD=%s is a git repository", pwd)
        if (pwd / ".git").exists():
            project_dir_str = str(pwd)
            os.environ["CLAUDE_PROJECT_DIR"] = project_dir_str
            log.info("SUCCESS: PWD contains .git directory, using as project root: %s", project_dir_str)
        else:
            log.error("FAILED: PWD does not contain .git directory, cannot detect project root")
            log.error("Project-specific setup will be skipped (no git pre-commit hooks, local registry)")

    # Install Bazelisk (downloads correct Bazel version automatically)
    bazelisk_setup.install_bazelisk()

    # Set up Bazel proxy for TLS-inspecting proxy
    # This now includes local registry setup if CLAUDE_PROJECT_DIR is set
    bazel_proxy_setup.setup_bazel_proxy()

    if project_dir_str:
        project_dir = Path(project_dir_str)
        log.info("Project directory confirmed: %s", project_dir)

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
    #
    # Claude Code web environment observations (v2.0.59):
    # - CLAUDE_ENV_FILE: NOT provided (despite docs saying SessionStart hooks get it)
    # - CLAUDE_PROJECT_DIR: NOT provided (despite docs saying hooks receive it)
    # - PATH already includes: /root/.local/bin (container default)
    #
    # Why ~/.local/bin instead of a more specific path?
    # - It's already on PATH in Claude Code web containers
    # - Standard XDG location for user executables
    # - More likely to persist across environment changes than custom paths
    # - Using CLAUDE_ENV_FILE would be better but it's not available
    log.info("Configuring bazel availability for bash sessions...")
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        log.info("CLAUDE_ENV_FILE provided: %s", env_file)
        log.info("Using standard approach: writing PATH export to CLAUDE_ENV_FILE")
        env_content = bazelisk_setup.get_env_script()
        # Also export the debug timestamp
        env_content += f'\nexport DUCKTAPE_SESSION_START_HOOK_TS="{hook_timestamp}"\n'
        # Export NODE_EXTRA_CA_CERTS to use combined CA bundle (includes Anthropic TLS inspection CA)
        # This allows Node.js tools (puppeteer, npm, etc.) to trust the proxy
        if bazel_proxy_setup.BAZEL_COMBINED_CA.exists():
            env_content += f'\nexport NODE_EXTRA_CA_CERTS="{bazel_proxy_setup.BAZEL_COMBINED_CA}"\n'
            log.info("Configured NODE_EXTRA_CA_CERTS to use combined CA bundle (for puppeteer, etc.)")
        Path(env_file).write_text(env_content)
        log.info("SUCCESS: Wrote PATH and timestamp exports to %s", env_file)
        log.info("Bazel will be available in bash sessions via PATH modification")
    else:
        log.warning("CLAUDE_ENV_FILE not provided by Claude Code (only available in SessionStart hooks)")
        log.warning("Cannot persist PATH modifications for bash sessions")
        log.info("Attempting fallback: symlinking bazel to ~/.local/bin (which is already on PATH)")

        local_bin = Path.home() / ".local" / "bin"

        # Defensive check: verify ~/.local/bin is on PATH
        log.info("Checking PATH environment variable...")
        current_path = os.environ.get("PATH", "")
        if str(local_bin) not in current_path:
            log.error("FAILED: %s is NOT in PATH - bazel symlink won't work", local_bin)
            log.error("Current PATH: %s", current_path)
            log.error("Bazel will not be available in bash sessions")
            emit_session_context(log, had_warnings=counter.warning_count > 0, had_errors=counter.error_count > 0)
            return 1
        log.info("CONFIRMED: %s is in PATH", local_bin)

        local_bin.mkdir(parents=True, exist_ok=True)
        log.info("Ensured %s exists", local_bin)

        bazel_symlink = local_bin / "bazel"
        bazel_wrapper = bazelisk_setup.WRAPPER_PATH

        # Defensive check: if bazel already exists, verify it's our symlink
        if bazel_symlink.exists() or bazel_symlink.is_symlink():
            if bazel_symlink.is_symlink():
                existing_target = bazel_symlink.resolve()
                if existing_target == bazel_wrapper.resolve():
                    log.info("Bazel symlink already points to our wrapper: %s -> %s", bazel_symlink, existing_target)
                    # Already configured correctly, continue to summary
                else:
                    log.warning(
                        "Existing bazel symlink points to different target: %s -> %s", bazel_symlink, existing_target
                    )
                    log.warning("Replacing with our wrapper")
                    bazel_symlink.unlink()
                    log.info("Removed existing bazel symlink at %s", bazel_symlink)
                    bazel_symlink.symlink_to(bazel_wrapper)
                    log.info("SUCCESS: Created symlink %s -> %s", bazel_symlink, bazel_wrapper)
            else:
                log.warning("Bazel exists but is not a symlink (file or directory): %s", bazel_symlink)
                log.warning("Replacing with our wrapper symlink")
                bazel_symlink.unlink()
                log.info("Removed existing bazel at %s", bazel_symlink)
                bazel_symlink.symlink_to(bazel_wrapper)
                log.info("SUCCESS: Created symlink %s -> %s", bazel_symlink, bazel_wrapper)
        else:
            bazel_symlink.symlink_to(bazel_wrapper)
            log.info("SUCCESS: Created symlink %s -> %s", bazel_symlink, bazel_wrapper)

        log.info("Bazel should be available in bash sessions via ~/.local/bin")

    # Set NODE_EXTRA_CA_CERTS for current session (needed for npm/puppeteer to trust proxy)
    if bazel_proxy_setup.BAZEL_COMBINED_CA.exists():
        os.environ["NODE_EXTRA_CA_CERTS"] = str(bazel_proxy_setup.BAZEL_COMBINED_CA)
        log.info("Set NODE_EXTRA_CA_CERTS=%s for current session", bazel_proxy_setup.BAZEL_COMBINED_CA)

    # Summary
    node_ca_status = "custom (with proxy CA)" if bazel_proxy_setup.BAZEL_COMBINED_CA.exists() else "system default"
    log.info("=" * 60)
    log.info("Environment ready:")
    log.info("  bazel:       %s", bazelisk_setup.get_status())
    log.info("  Bazel proxy: %s", bazel_proxy_setup.get_status())
    log.info("  git hook:    installed (pre-commit)")
    log.info("  Node.js CA:  %s", node_ca_status)
    log.info("=" * 60)

    # Emit context for Claude Code to inject into transcript
    emit_session_context(log, had_warnings=counter.warning_count > 0, had_errors=counter.error_count > 0)

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
