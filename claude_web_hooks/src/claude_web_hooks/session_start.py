#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv."""

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

from claude_web_hooks.streaming import run_streaming

from claude_web_hooks import nix_setup

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv", "uv"]

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger(__name__)


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
    nix_store_bin = nix_setup.install_nix(project_dir, run_streaming)

    # Install tools using the store path directly
    nix_setup.install_tools(nix_store_bin, TOOLS, run_streaming)

    # Allow .envrc files
    if shutil.which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            log.info("Allowing direnv for: %s", envrc.parent)
            run_streaming(["direnv", "allow", str(envrc.parent)], check=False)

    # Persist environment with both store bin and profile bin
    nix_setup.persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    log.info("=" * 60)
    log.info("Session environment initialized:")
    for tool in ["nix", *TOOLS]:
        if path := shutil.which(tool):
            result = subprocess.run([tool, "--version"], capture_output=True, text=True, check=False)
            version = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?"
            log.info("  %-10s %s (%s)", tool + ":", version, path)
        else:
            log.info("  %-10s N/A", tool + ":")
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
