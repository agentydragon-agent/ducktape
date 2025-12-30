#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, and Bazel proxy."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "claude-code-web"
LOG_FILE = CACHE_DIR / "session-start.log"
TOOLS = ["direnv", "devenv"]


def setup_logging() -> logging.Logger:
    """Configure logging to stdout and file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
    )
    return logging.getLogger(__name__)


def load_module(name: str, path: Path):
    """Load a Python module from filesystem path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    log = setup_logging()
    hook_dir = Path(__file__).parent / "claude-code-web"

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

    # Load modules lazily to avoid import-time side effects
    streaming = load_module("streaming", hook_dir / "streaming.py")
    nix_setup = load_module("nix_setup", hook_dir / "nix_setup.py")
    bazel_proxy = load_module("bazel_proxy_setup", hook_dir / "bazel_proxy_setup.py")

    log.info("Setting up dev environment...")

    # Install nix and get the store bin path
    nix_store_bin = nix_setup.install_nix(project_dir, streaming.run_streaming)

    # Install tools
    nix_setup.install_tools(nix_store_bin, TOOLS, streaming.run_streaming)

    # Allow .envrc files
    if shutil.which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            log.info("Allowing direnv: %s", envrc.parent)
            streaming.run_streaming(["direnv", "allow", str(envrc.parent)], check=False)

    # Persist environment
    nix_setup.persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    # Set up Bazel proxy for TLS-inspecting proxy
    bazel_proxy.setup_bazel_proxy()

    # Summary
    log.info("=" * 60)
    log.info("Environment ready:")
    for tool in ["nix", *TOOLS, "bazel"]:
        path = shutil.which(tool)
        if path:
            result = subprocess.run([tool, "--version"], capture_output=True, text=True, check=False)
            version = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?"
            log.info("  %-10s %s (%s)", tool + ":", version, path)
        else:
            log.info("  %-10s not installed", tool + ":")
    log.info("  Bazel proxy: %s", bazel_proxy.get_status())
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
