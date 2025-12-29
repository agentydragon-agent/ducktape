#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv."""

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv", "uv"]

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
log = logging.getLogger(__name__)


def log_diagnostics() -> None:
    """Log network and environment diagnostics."""
    log.info("=== Diagnostics ===")

    # Check network connectivity
    start = time.time()
    result = subprocess.run(
        ["curl", "-sI", "--connect-timeout", "5", "https://cache.nixos.org"],
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - start
    status = result.stdout.split("\n")[0] if result.returncode == 0 else f"failed: {result.returncode}"
    log.info("  cache.nixos.org: %s (%.2fs)", status.strip(), elapsed)

    # Check proxy settings
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        val = os.environ.get(var, "")
        if val:
            # Truncate long JWT tokens
            if "jwt_" in val:
                val = val[:60] + "...[truncated]"
            log.info("  %s: %s", var, val)

    # Check if we're in a resumed session (nix store already populated)
    nix_store = Path("/nix/store")
    if nix_store.exists():
        entries = list(nix_store.iterdir())
        log.info("  /nix/store entries: %d", len(entries))
    else:
        log.info("  /nix/store: does not exist")

    log.info("=== End Diagnostics ===")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run command with check=True, logging output."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in (result.stdout + result.stderr).strip().split("\n"):
        if line:
            log.info("  %s", line)
    return result


def which(cmd: str) -> str | None:
    """Find command in PATH."""
    result = subprocess.run(["which", cmd], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


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
        log.info("Added to PATH: %s", ", ".join(map(str, paths)))


def install_nix(project_dir: Path) -> Path:
    """Install nix if not present. Returns the nix store bin path."""
    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    if nix_conf.exists():
        os.environ["NIX_USER_CONF_FILES"] = str(nix_conf)
        log.info("Using nix.conf: %s", nix_conf)

    # Check if nix is already in the store
    nix_store_bin = find_nix_bin()
    if nix_store_bin:
        log.info("nix already in store: %s", nix_store_bin)
        setup_nix_path(nix_store_bin)
        return nix_store_bin

    log.info("Installing nix...")
    start = time.time()
    subprocess.run(
        ["curl", "-sL", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"],
        check=True,
    )
    log.info("  Downloaded nix installer in %.1fs", time.time() - start)

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
    start = time.time()
    subprocess.run(
        ["sh", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    log.info("  Ran nix installer in %.1fs", time.time() - start)

    nix_store_bin = find_nix_bin()
    if not nix_store_bin:
        raise RuntimeError("Failed to install nix - no nix binary found in store")

    log.info("nix installed: %s", nix_store_bin)
    setup_nix_path(nix_store_bin)
    return nix_store_bin


def install_tools(nix_store_bin: Path, tools: list[str]) -> None:
    """Install tools via nix profile using the store path directly.

    Uses the nix binary from the store path, NOT from PATH or profile.
    This avoids the issue where `nix profile install` replaces the profile
    and removes nix from PATH.
    """
    nix_cmd = nix_store_bin / "nix"
    nix_conf = os.environ.get("NIX_USER_CONF_FILES", "")

    # Filter out tools that are already available
    missing_tools = [t for t in tools if not which(t)]
    if not missing_tools:
        log.info("All tools already available: %s", ", ".join(tools))
        return

    log.info("Installing tools: %s", ", ".join(missing_tools))

    # Install all missing tools in one command
    cmd = [str(nix_cmd), "profile", "install"] + [f"nixpkgs#{t}" for t in missing_tools]
    log.info("Running: %s", " ".join(cmd))
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start
    log.info("nix profile install completed in %.1fs (exit code: %d)", elapsed, result.returncode)

    for line in (result.stdout + result.stderr).strip().split("\n"):
        if line:
            log.info("  %s", line)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to install tools: {result.stderr}")

    log.info("Tools installed successfully")


def persist_environment(env_file: str | None, nix_store_bin: Path, project_dir: Path) -> None:
    """Write environment to CLAUDE_ENV_FILE for persistence.

    Persists BOTH the nix store bin (for running nix commands) AND the
    profile bin (for user-installed tools like direnv, devenv).
    """
    if not env_file:
        log.warning("CLAUDE_ENV_FILE is empty, PATH changes will not persist")
        return

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    content = f'''# Nix environment (added by session-start-direnv.py)
export NIX_USER_CONF_FILES="{nix_conf}"
# Nix store bin for running nix commands (immutable, always available)
[ -d "{nix_store_bin}" ] && export PATH="{nix_store_bin}:$PATH"
# Profile bin for user-installed tools (direnv, devenv, etc.)
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"
'''
    Path(env_file).write_text(content)
    log.info("Wrote environment to CLAUDE_ENV_FILE=%s", env_file)


def main() -> int:
    start_time = time.time()
    log.info("Starting hook at %s", datetime.now().isoformat())

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    # Log diagnostics early (before any installs)
    log_diagnostics()

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
    if which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            subprocess.run(["direnv", "allow", str(envrc.parent)], capture_output=True)

    # Persist environment with both store bin and profile bin
    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    log.info("Session environment initialized:")
    for tool in ["nix"] + TOOLS:
        if path := which(tool):
            result = subprocess.run([tool, "--version"], capture_output=True, text=True)
            log.info("  %s: %s", tool, result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?")
        else:
            log.info("  %s: N/A", tool)

    total_elapsed = time.time() - start_time
    log.info("Setup complete (total: %.1fs)", total_elapsed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("Hook failed: %s", e)
        log.error(traceback.format_exc())
        sys.exit(1)
