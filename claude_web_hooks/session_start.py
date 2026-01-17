#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up Bazel proxy and git hooks."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from claude_web_hooks import bazel_proxy_setup, bazelisk_setup, cluster_tools, nix_setup
from claude_web_hooks.streaming import run_streaming

CACHE_DIR = Path.home() / ".cache" / "claude-code-web"
LOG_FILE = CACHE_DIR / "session-start.log"


def get_nix_tools_status() -> str:
    """Get status of nix-installed tools for pre-commit hooks."""
    tools = ["alejandra"]
    available = [t for t in tools if shutil.which(t)]
    missing = [t for t in tools if t not in available]
    if missing and not available:
        return f"missing ({', '.join(missing)})"
    if missing:
        return f"partial ({', '.join(available)}; missing: {', '.join(missing)})"
    return f"installed ({', '.join(available)})"


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


def setup_podman_storage(log: logging.Logger) -> None:
    """Configure podman for gVisor compatibility.

    gVisor sandbox has restrictions that require specific podman configuration:
    1. VFS storage driver (no overlay filesystem support)
    2. System-level config (/etc/containers) since running as root
    3. Explicit runroot and graphroot paths
    4. Host user namespace (userns = "host")
    """
    # Storage configuration (system-level since running as root)
    storage_conf = Path("/etc/containers/storage.conf")
    storage_conf.parent.mkdir(parents=True, exist_ok=True)
    storage_conf.write_text("""[storage]
driver = "vfs"
runroot = "/run/containers/storage"
graphroot = "/var/lib/containers/storage"
""")

    # Container runtime configuration
    containers_conf = Path("/etc/containers/containers.conf")
    containers_conf.write_text("""[containers]
# Host user namespace for gVisor compatibility
userns = "host"

[engine]
network_backend = "cni"
""")

    # Ensure storage directories exist
    Path("/run/containers/storage").mkdir(parents=True, exist_ok=True)
    Path("/var/lib/containers/storage").mkdir(parents=True, exist_ok=True)

    log.info("Configured podman for gVisor: VFS storage, host userns")


def setup_props_environment(log: logging.Logger) -> None:
    """Set environment variables for props e2e testing with podman + host networking."""
    env_file_str = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file_str:
        log.warning("CLAUDE_ENV_FILE not set, cannot configure props environment")
        return

    # Podman + host networking configuration
    env_content = """
# Props e2e test configuration (podman + host networking)
export PGHOST=127.0.0.1
export PGPORT=5433
export AGENT_PGHOST=127.0.0.1
export PROPS_REGISTRY_PROXY_HOST=127.0.0.1
export PROPS_REGISTRY_PROXY_PORT=5051
export PROPS_DOCKER_NETWORK=host
"""

    env_file = Path(env_file_str)
    with env_file.open("a") as f:
        f.write(env_content)

    log.info("Configured props environment variables for podman + host networking")


def emit_podman_guidance() -> None:
    """Emit podman usage guidance for gVisor sandbox (visible to agent)."""
    guidance = """
Podman Usage in gVisor Sandbox
===============================

Podman is configured with gVisor-specific workarounds. All containers MUST use:

  --annotation run.oci.keep_original_groups=1

This bypasses /proc/self/setgroups which is unavailable in gVisor.

Required Flags for ALL Container Runs:
--------------------------------------
podman run --annotation run.oci.keep_original_groups=1 [other-flags] image

Example (simple):
  podman run --rm --network=host \\
    --annotation run.oci.keep_original_groups=1 \\
    alpine echo "Hello"

Example (postgres):
  podman run -d --rm --network=host \\
    --annotation run.oci.keep_original_groups=1 \\
    --name postgres -e POSTGRES_PASSWORD=pass \\
    docker.io/library/postgres:16 postgres -p 5433

Configuration Applied:
---------------------
- Storage: VFS (/etc/containers/storage.conf)
- User namespace: host (userns = "host")
- Networking: host networking recommended (--network=host)
- Image names: use fully qualified names (docker.io/library/...)

Without --annotation run.oci.keep_original_groups=1, containers will fail with:
  "crun: error opening file `/proc/self/setgroups`: No such file or directory"

"""
    print(guidance)
    sys.stdout.flush()


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

        # Install cluster tools if cluster/ directory exists (for pre-commit hooks)
        cluster_dir = project_dir / "cluster"
        if cluster_dir.is_dir():
            verbose.info("Installing cluster tools for pre-commit hooks...")
            results = cluster_tools.install_all()
            for tool, success in results.items():
                if success:
                    verbose.info("  %s: installed", tool)
                else:
                    verbose.warning("  %s: failed to install", tool)

        # Install nix + alejandra for nix file formatting (pre-commit hook)
        # TODO: Switch to nixfmt (RFC style) once it has better pre-built binary support
        nix_files_exist = any(project_dir.rglob("*.nix"))
        if nix_files_exist:
            verbose.info("Installing nix + alejandra for .nix formatting...")
            try:
                nix_store_bin = nix_setup.install_nix(project_dir, run_streaming)
                nix_setup.install_tools(nix_store_bin, ["alejandra"], run_streaming)
                verbose.info("alejandra installed successfully")
            except Exception as e:
                verbose.warning("Failed to install nix/alejandra: %s", e)

        # Configure podman and props environment if props directory exists
        props_dir = project_dir / "props"
        if props_dir.is_dir():
            verbose.info("Configuring podman and props environment for e2e testing...")
            setup_podman_storage(verbose)
            setup_props_environment(verbose)
            # Emit usage guidance visible to agent
            emit_podman_guidance()
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
        # Read existing content (may include props environment from setup_props_environment)
        env_path = Path(env_file)
        existing_content = env_path.read_text() if env_path.exists() else ""

        repo_root = Path(project_dir_str) if project_dir_str else None
        env_content = bazelisk_setup.get_env_script(bazel_proxy_setup.BAZEL_PROXY_PORT, repo_root=repo_root)
        env_content += f'\nexport DUCKTAPE_SESSION_START_HOOK_TS="{hook_timestamp}"\n'
        if bazel_proxy_setup.BAZEL_COMBINED_CA.exists():
            env_content += f'\nexport NODE_EXTRA_CA_CERTS="{bazel_proxy_setup.BAZEL_COMBINED_CA}"\n'
        # Add nix profile to PATH for alejandra and other nix-installed tools
        nix_profile_bin = Path.home() / ".nix-profile" / "bin"
        if nix_profile_bin.exists():
            env_content += f'\nexport PATH="{nix_profile_bin}:$PATH"\n'

        # Append to existing content (preserves props environment variables)
        full_content = existing_content + env_content
        env_path.write_text(full_content)
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
    # Show cluster tools status if cluster/ exists
    if project_dir_str and (Path(project_dir_str) / "cluster").is_dir():
        log.info("Cluster tools: %s", cluster_tools.get_status())
    # Show nix tools status if .nix files exist
    if project_dir_str and any(Path(project_dir_str).rglob("*.nix")):
        log.info("Nix tools: %s", get_nix_tools_status())

    # Emit supervisor usage guidance if proxy is running
    if bazel_proxy_setup.is_configured():
        from claude_web_hooks import supervisor_setup

        supervisor_setup.emit_usage_guidance()

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
