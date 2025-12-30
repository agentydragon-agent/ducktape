#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, and Bazel proxy."""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import traceback

# Add claude-code-web to path for imports
sys.path.insert(0, str(Path(__file__).parent / "claude-code-web"))

from streaming import run_streaming  # noqa: E402 - path setup required
from nix_setup import install_nix, install_tools, persist_environment, which  # noqa: E402
from bazel_proxy_setup import setup_bazel_proxy, get_status as get_bazel_proxy_status  # noqa: E402

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv"]

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger(__name__)


def allow_envrc_files(project_dir: Path) -> None:
    """Allow all .envrc files in the project."""
    if not which("direnv"):
        return
    for envrc in project_dir.rglob(".envrc"):
        log.info("Allowing direnv for: %s", envrc.parent)
        run_streaming(
            ["direnv", "allow", str(envrc.parent)],
            f"direnv allow {envrc.parent.name}",
            check=False,
        )


def log_tool_versions(tools: list[str]) -> None:
    """Log versions of installed tools."""
    for tool in tools:
        if path := which(tool):
            result = subprocess.run([tool, "--version"], capture_output=True, text=True, check=False)
            version = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?"
            log.info("  %-10s %s (%s)", tool + ":", version, path)
        else:
            log.info("  %-10s N/A", tool + ":")


def main() -> int:
    log.info("=" * 60)
    log.info("Starting hook at %s", datetime.now().isoformat())
    log.info("=" * 60)
    log.info("Environment: %s", json.dumps(dict(os.environ), sort_keys=True, indent=2))

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir:
        raise RuntimeError("CLAUDE_PROJECT_DIR not set")
    project_dir = Path(project_dir)

    log.info("Setting up dev environment...")

    # Install nix and get the store bin path (used for all subsequent nix commands)
    nix_store_bin = install_nix(project_dir)

    # Install tools using the store path directly
    install_tools(nix_store_bin, TOOLS)

    # Allow .envrc files
    allow_envrc_files(project_dir)

    # Persist environment with both store bin and profile bin
    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    # Set up Bazel proxy for TLS-inspecting proxy (Claude Code web specific)
    setup_bazel_proxy()

    log.info("=" * 60)
    log.info("Session environment initialized:")
    log_tool_versions(["nix", *TOOLS, "bazel"])
    log.info("  Bazel proxy: %s", get_bazel_proxy_status())
    log.info("=" * 60)
    log.info("Setup complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("=" * 60)
        log.error("Hook failed: %s", e)
        log.error("=" * 60)
        log.error(traceback.format_exc())
        sys.exit(1)
