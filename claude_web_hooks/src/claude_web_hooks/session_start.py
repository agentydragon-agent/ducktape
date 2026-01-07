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


def format_environment_summary() -> str:
    """Format a compact environment summary with deduplicated proxy values."""
    env = dict(os.environ)

    # Group env vars by their value to deduplicate long proxy URLs
    value_to_vars: dict[str, list[str]] = {}
    for key, value in sorted(env.items()):
        if value not in value_to_vars:
            value_to_vars[value] = []
        value_to_vars[value].append(key)

    lines = []

    # Find proxy-related values (long URLs that appear in multiple vars)
    proxy_vars = {}
    other_vars = {}

    for value, keys in value_to_vars.items():
        # Identify proxy values by checking if they're long URLs used by multiple vars
        is_proxy = len(value) > 100 and any(
            k for k in keys if "PROXY" in k.upper() or k in ("http_proxy", "https_proxy")
        )
        if is_proxy and len(keys) > 1:
            proxy_vars[value] = keys
        else:
            for key in keys:
                other_vars[key] = value

    # Output proxy values with their aliases
    if proxy_vars:
        lines.append("Proxy configuration:")
        for i, (value, keys) in enumerate(proxy_vars.items(), 1):
            # Truncate the URL for display
            truncated = value[:80] + "..." if len(value) > 80 else value
            lines.append(f"  proxy_{i}: {truncated}")
            lines.append(f"    Used by: {', '.join(sorted(keys))}")

    # Output key environment vars (not all, just important ones)
    important_keys = [
        "CLAUDE_CODE_REMOTE",
        "CLAUDE_CODE_VERSION",
        "CLAUDE_PROJECT_DIR",
        "CLAUDE_ENV_FILE",
        "NODE_EXTRA_CA_CERTS",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "DOCKER_HOST",
        "PATH",
    ]

    lines.append("Key environment:")
    for key in important_keys:
        if key in other_vars:
            value = other_vars[key]
            # Truncate long values
            if len(value) > 100:
                value = value[:97] + "..."
            lines.append(f"  {key}={value}")

    return "\n".join(lines)


def emit_session_context(had_warnings: bool, had_errors: bool) -> None:
    """Emit compact context summary for Claude Code transcript.

    This goes to stdout and gets injected as context for the agent.
    Keep this minimal - verbose details go to the log file.
    """
    lines = ["=" * 60, "Claude Code on the web (gVisor sandbox)", "=" * 60]

    # Status line
    if had_errors:
        lines.append("Status: ERRORS - check log for details")
    elif had_warnings:
        lines.append("Status: OK with warnings")
    else:
        lines.append("Status: OK")

    # Key constraints and skills
    lines.extend(
        [
            "",
            "Environment constraints:",
            "  - TLS-inspecting proxy (custom CA configured)",
            "  - No overlay filesystem (use vfs for containers)",
            "  - Network via proxy only (no direct DNS)",
            "",
            "Available skill: github-actions-web",
            "  Run CI workflows locally with: act + podman",
            "  See .claude/skills/github-actions-web/SKILL.md",
            "",
            f"Full log: {LOG_FILE}",
            "=" * 60,
        ]
    )

    print("\n".join(lines))
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


class SessionLoggers:
    """Container for stdout (compact) and file-only (verbose) loggers."""

    def __init__(self, stdout_logger: logging.Logger, file_logger: logging.Logger, counter: LogLevelCounter):
        self.stdout = stdout_logger  # Goes to both stdout and file
        self.file = file_logger  # Goes to file only (for verbose output)
        self.counter = counter


def setup_logging() -> SessionLoggers:
    """Configure split logging: compact to stdout, verbose to file only.

    Returns SessionLoggers with separate loggers for stdout vs file-only output.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Format with clear log level indicators
    class LogLevelFormatter(logging.Formatter):
        def format(self, record):
            if record.levelno == logging.INFO:
                return record.getMessage()
            if record.levelno == logging.WARNING:
                return f"[WARNING] {record.getMessage()}"
            if record.levelno == logging.ERROR:
                return f"[ERROR] {record.getMessage()}"
            return f"[{record.levelname}] {record.getMessage()}"

    formatter = LogLevelFormatter()
    counter = LogLevelCounter()

    # Stdout logger: goes to both stdout and file
    stdout_logger = logging.getLogger(f"{__name__}.stdout")
    stdout_logger.setLevel(logging.INFO)
    stdout_logger.propagate = False

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_logger.addHandler(stdout_handler)

    file_handler_stdout = logging.FileHandler(LOG_FILE, mode="a")
    file_handler_stdout.setFormatter(formatter)
    stdout_logger.addHandler(file_handler_stdout)
    stdout_logger.addHandler(counter)

    # File-only logger: verbose details that don't go to stdout
    file_logger = logging.getLogger(f"{__name__}.file")
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False

    file_handler_only = logging.FileHandler(LOG_FILE, mode="a")
    file_handler_only.setFormatter(formatter)
    file_logger.addHandler(file_handler_only)
    file_logger.addHandler(counter)

    return SessionLoggers(stdout_logger, file_logger, counter)


def main() -> int:
    loggers = setup_logging()
    log = loggers.stdout  # Compact output to stdout + file
    verbose = loggers.file  # Verbose output to file only

    # Compact header for stdout
    log.info("Session start hook: %s", datetime.now().isoformat())

    # Verbose header for file only
    verbose.info("=" * 60)
    verbose.info("Hook: %s", __file__)
    verbose.info("Time: %s", datetime.now().isoformat())
    verbose.info("Log:  %s", LOG_FILE)
    verbose.info("=" * 60)

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping setup")
        emit_session_context(had_warnings=False, had_errors=False)
        return 0

    # Full environment dump goes to file only (too verbose for stdout)
    verbose.info("Full environment:\n%s", json.dumps(dict(os.environ), sort_keys=True, indent=2))

    # Compact environment summary for stdout
    log.info("Setting up dev environment...")
    log.info(format_environment_summary())

    # Detect project directory
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir_str:
        verbose.info("CLAUDE_PROJECT_DIR provided: %s", project_dir_str)
    else:
        verbose.warning("CLAUDE_PROJECT_DIR not provided (fallback to PWD)")
        pwd = Path.cwd()
        if (pwd / ".git").exists():
            project_dir_str = str(pwd)
            os.environ["CLAUDE_PROJECT_DIR"] = project_dir_str
            log.info("Project: %s", project_dir_str)
        else:
            log.error("Cannot detect project root (no .git)")

    # Install Bazelisk
    bazelisk_setup.install_bazelisk()

    # Set up Bazel proxy
    bazel_proxy_setup.setup_bazel_proxy()

    if project_dir_str:
        project_dir = Path(project_dir_str)
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=project_dir)
        install_git_precommit_hook(project_dir, verbose)  # Detailed logging to file
    else:
        bazelisk_setup.install_wrapper(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=None)

    # Export debug timestamp
    hook_timestamp = datetime.now().isoformat()
    os.environ["DUCKTAPE_SESSION_START_HOOK_TS"] = hook_timestamp
    timestamp_file = Path.home() / ".ducktape_session_hook_last_run"
    timestamp_file.write_text(f"{hook_timestamp}\n")
    verbose.info("Session start hook timestamp: %s", hook_timestamp)

    # Configure PATH for bash sessions
    verbose.info("Configuring bazel availability for bash sessions...")
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        env_content = bazelisk_setup.get_env_script()
        env_content += f'\nexport DUCKTAPE_SESSION_START_HOOK_TS="{hook_timestamp}"\n'
        if bazel_proxy_setup.BAZEL_COMBINED_CA.exists():
            env_content += f'\nexport NODE_EXTRA_CA_CERTS="{bazel_proxy_setup.BAZEL_COMBINED_CA}"\n'
        Path(env_file).write_text(env_content)
        verbose.info("Wrote PATH exports to %s", env_file)
    else:
        # Fallback: symlink bazel to ~/.local/bin
        verbose.warning("CLAUDE_ENV_FILE not provided, using symlink fallback")
        local_bin = Path.home() / ".local" / "bin"
        current_path = os.environ.get("PATH", "")
        if str(local_bin) not in current_path:
            log.error("~/.local/bin not in PATH - bazel won't be available")
            emit_session_context(
                had_warnings=loggers.counter.warning_count > 0, had_errors=loggers.counter.error_count > 0
            )
            return 1

        local_bin.mkdir(parents=True, exist_ok=True)
        bazel_symlink = local_bin / "bazel"
        bazel_wrapper = bazelisk_setup.WRAPPER_PATH

        if bazel_symlink.exists() or bazel_symlink.is_symlink():
            if bazel_symlink.is_symlink() and bazel_symlink.resolve() == bazel_wrapper.resolve():
                verbose.info("Bazel symlink already configured")
            else:
                verbose.warning("Replacing existing bazel with symlink")
                bazel_symlink.unlink()
                bazel_symlink.symlink_to(bazel_wrapper)
        else:
            bazel_symlink.symlink_to(bazel_wrapper)
            verbose.info("Created bazel symlink: %s -> %s", bazel_symlink, bazel_wrapper)

    # Set NODE_EXTRA_CA_CERTS for current session
    if bazel_proxy_setup.BAZEL_COMBINED_CA.exists():
        os.environ["NODE_EXTRA_CA_CERTS"] = str(bazel_proxy_setup.BAZEL_COMBINED_CA)

    # Compact summary for stdout
    node_ca_status = "custom CA" if bazel_proxy_setup.BAZEL_COMBINED_CA.exists() else "system"
    log.info(
        "Ready: bazel=%s, proxy=%s, CA=%s", bazelisk_setup.get_status(), bazel_proxy_setup.get_status(), node_ca_status
    )

    # Emit context for Claude Code
    emit_session_context(had_warnings=loggers.counter.warning_count > 0, had_errors=loggers.counter.error_count > 0)

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
