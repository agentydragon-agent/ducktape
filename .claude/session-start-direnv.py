#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv."""

import json
import logging
import os
import subprocess
import sys
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


def setup_nix_path() -> None:
    """Add nix to PATH."""
    paths = [p for p in [find_nix_bin(), Path.home() / ".nix-profile" / "bin"] if p and p.exists()]
    if paths:
        os.environ["PATH"] = ":".join(map(str, paths)) + ":" + os.environ.get("PATH", "")
        log.info("Added to PATH: %s", ", ".join(map(str, paths)))


def install_nix(project_dir: Path) -> None:
    """Install nix if not present."""
    if which("nix"):
        log.info("nix already available")
        return

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    if nix_conf.exists():
        os.environ["NIX_USER_CONF_FILES"] = str(nix_conf)
        log.info("Using nix.conf: %s", nix_conf)

    log.info("Installing nix...")
    subprocess.run(
        ["curl", "-sL", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"],
        check=True,
    )

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
    # GVISOR BUG LOCATION (github.com/google/gvisor):
    # pkg/sentry/fsimpl/devpts/queue.go lines 112-116:
    #   if !q.readable {
    #       if l.numReplicas == 0 {
    #           return 0, false, false, linuxerr.EIO  // ← THE BUG
    #       }
    #       return 0, false, false, linuxerr.ErrWouldBlock
    #   }
    # gVisor returns EIO when numReplicas==0 (no slave opened yet), but the child
    # process is still in the middle of opening the slave. Real Linux blocks until
    # data arrives regardless of whether the slave has been opened. gVisor conflates
    # "not yet opened" with "closed" - both result in numReplicas==0.
    #
    # WHY NIX USES PTYs (not pipes):
    # Per C99 7.19.3, stdout is fully buffered when connected to a pipe, but line
    # buffered when connected to a terminal. Nix needs real-time build output, so it
    # uses PTYs to trick programs into line-buffered mode. This is fundamental to
    # Nix's architecture - there's no --use-pipes flag.
    # See: src/libstore/unix/build/derivation-builder.cc line 808 (posix_openpt)
    #
    # WHY NO INSTALLER FLAGS HELP:
    # - The PTY is created internally by nix-env, not inherited from the shell
    # - --no-daemon, --no-channel-add, </dev/null all affect different things
    # - sandbox=false in nix.conf disables namespace isolation, not PTY usage
    # - The gVisor bug is in read() returning EIO, not in any Nix configuration
    #
    # WORKAROUND:
    # Skip nix-env entirely. The installer already unpacked Nix to /nix/store.
    # We just symlink the profile manually, bypassing any derivation builds.
    subprocess.run(
        ["sh", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )

    # Manual profile setup when installer's nix-env fails due to gVisor PTY bug.
    nix_profile = Path.home() / ".nix-profile"
    if not (nix_profile / "bin" / "nix").exists():
        nix_bin = find_nix_bin()
        if nix_bin:
            nix_pkg = nix_bin.parent
            profiles_dir = Path("/nix/var/nix/profiles/per-user/root")
            profiles_dir.mkdir(parents=True, exist_ok=True)
            (profiles_dir / "profile").unlink(missing_ok=True)
            (profiles_dir / "profile").symlink_to(nix_pkg)
            nix_profile.unlink(missing_ok=True)
            nix_profile.symlink_to(profiles_dir / "profile")
            log.info("Created manual profile link: %s", nix_pkg)

    setup_nix_path()
    if not which("nix"):
        raise RuntimeError("Failed to install nix")


def install_tool(tool: str) -> None:
    """Install a tool via nix profile."""
    if which(tool):
        log.info("%s already available", tool)
        return
    log.info("Installing %s...", tool)
    run(["nix", "profile", "install", f"nixpkgs#{tool}"])
    log.info("%s installed", tool)


def persist_environment(env_file: str | None, project_dir: Path) -> None:
    """Write environment to CLAUDE_ENV_FILE for persistence."""
    if not env_file:
        log.warning("CLAUDE_ENV_FILE is empty, PATH changes will not persist")
        return

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    nix_bin = find_nix_bin()
    content = f'''# Nix environment (added by session-start-direnv.py)
export NIX_USER_CONF_FILES="{nix_conf}"
[ -d "{nix_bin}" ] && export PATH="{nix_bin}:$PATH"
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"
'''
    Path(env_file).write_text(content)
    log.info("Wrote environment to CLAUDE_ENV_FILE=%s", env_file)


def main() -> int:
    log.info("Starting hook at %s", datetime.now().isoformat())
    log.info("Environment: %s", json.dumps(dict(os.environ), sort_keys=True))

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir:
        raise RuntimeError("CLAUDE_PROJECT_DIR not set")
    project_dir = Path(project_dir)

    log.info("Setting up dev environment...")
    install_nix(project_dir)

    for tool in TOOLS:
        install_tool(tool)

    # Allow .envrc files
    if which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            subprocess.run(["direnv", "allow", str(envrc.parent)], capture_output=True)

    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), project_dir)

    log.info("Session environment initialized:")
    for tool in ["nix"] + TOOLS:
        if path := which(tool):
            result = subprocess.run([tool, "--version"], capture_output=True, text=True)
            log.info("  %s: %s", tool, result.stdout.strip().split("\n")[0] if result.returncode == 0 else "?")
        else:
            log.info("  %s: N/A", tool)

    log.info("Setup complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("Hook failed: %s", e)
        log.error(traceback.format_exc())
        sys.exit(1)
