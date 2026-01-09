"""Nix installation and tool setup for Claude Code web sessions."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def find_nix_bin() -> Path | None:
    """Find nix binary directory in /nix/store."""
    nix_store = Path("/nix/store")
    if not nix_store.exists():
        return None
    for entry in sorted(nix_store.iterdir(), reverse=True):
        if "-nix-" in entry.name:
            bin_dir = entry / "bin"
            if bin_dir.exists() and (bin_dir / "nix").exists():
                return bin_dir
    return None


def setup_nix_path(nix_store_bin: Path) -> None:
    """Add nix store bin and profile bin to PATH."""
    paths = [nix_store_bin, Path.home() / ".nix-profile" / "bin"]
    paths = [p for p in paths if p.exists()]
    if paths:
        os.environ["PATH"] = ":".join(map(str, paths)) + ":" + os.environ.get("PATH", "")
        logger.info("Added to PATH: %s", ", ".join(map(str, paths)))


def get_nix_conf_path(project_dir: Path) -> Path:
    """Get the path to project-specific nix.conf."""
    return project_dir / ".claude" / "claude-code-web" / "nix.conf"


def install_nix(project_dir: Path, run_streaming: Callable[..., int]) -> Path:
    """Install nix if not present. Returns the nix store bin path."""
    nix_conf = get_nix_conf_path(project_dir)
    if nix_conf.exists():
        os.environ["NIX_USER_CONF_FILES"] = str(nix_conf)
        logger.info("Using nix.conf: %s", nix_conf)

    # Check if nix is already in the store
    nix_store_bin = find_nix_bin()
    if nix_store_bin:
        logger.info("nix already in store: %s", nix_store_bin)
        setup_nix_path(nix_store_bin)
        return nix_store_bin

    logger.info("Installing nix...")

    # Download with progress bar
    run_streaming(["curl", "--progress-bar", "-L", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"])

    # The nix-env step fails in gVisor containers due to a PTY bug.
    # nix-env opens /dev/ptmx, forks a sandbox process, then reads from the PTY master.
    # gVisor returns EIO on this read (race condition in PTY emulation).
    #
    # ROOT CAUSE (discovered via strace):
    # Claude Code web runs on gVisor (runsc), not a real Linux kernel. gVisor's PTY
    # emulation has a race condition. When nix-env builds a derivation, it:
    #   1. Opens /dev/ptmx to create a PTY pair (master fd)
    #   2. Forks a child process for the build sandbox
    #   3. Parent immediately calls read() on the PTY master
    #   4. gVisor returns EIO instead of blocking until data arrives
    #
    # WORKAROUND:
    # Skip nix-env entirely. The installer already unpacked Nix to /nix/store.
    # We use the store path directly instead of relying on profiles.
    run_streaming(
        ["sh", "-x", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        check=False,  # Installer may fail on nix-env step, that's OK
    )

    nix_store_bin = find_nix_bin()
    if not nix_store_bin:
        raise RuntimeError("Failed to install nix - no nix binary found in store")

    logger.info("nix installed: %s", nix_store_bin)
    setup_nix_path(nix_store_bin)
    return nix_store_bin


def install_tools(nix_store_bin: Path, tools: list[str], run_streaming: Callable[..., int]) -> None:
    """Install tools via nix profile using the store path directly.

    Uses the nix binary from the store path, NOT from PATH or profile.
    This avoids the issue where `nix profile install` replaces the profile
    and removes nix from PATH.
    """
    nix_cmd = nix_store_bin / "nix"

    # Filter out tools that are already available
    missing_tools = [t for t in tools if not shutil.which(t)]
    if not missing_tools:
        logger.info("All tools already available: %s", ", ".join(tools))
        return

    logger.info("Installing tools: %s", ", ".join(missing_tools))

    # Install all missing tools in one command with verbose output
    # -v: verbose, --print-build-logs: show build output
    cmd = [str(nix_cmd), "profile", "install", "-v", "--print-build-logs"] + [f"nixpkgs#{t}" for t in missing_tools]

    run_streaming(cmd)

    logger.info("Tools installed successfully")


def persist_environment(env_file: str | None, nix_store_bin: Path, nix_conf: Path) -> None:
    """Write environment to CLAUDE_ENV_FILE for persistence.

    Persists BOTH the nix store bin (for running nix commands) AND the
    profile bin (for user-installed tools like direnv, devenv).
    """
    if not env_file:
        logger.warning("CLAUDE_ENV_FILE is empty, PATH changes will not persist")
        return

    content = f'''# Nix environment (added by session-start-direnv.py)
export NIX_USER_CONF_FILES="{nix_conf}"
# Nix store bin for running nix commands (immutable, always available)
[ -d "{nix_store_bin}" ] && export PATH="{nix_store_bin}:$PATH"
# Profile bin for user-installed tools (direnv, devenv, etc.)
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"
'''
    Path(env_file).write_text(content)
    logger.info("Wrote environment to CLAUDE_ENV_FILE=%s", env_file)
