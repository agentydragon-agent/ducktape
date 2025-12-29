#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback
from typing import IO

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv", "uv"]

logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, mode="a")],
)
log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0


@contextmanager
def heartbeat(operation: str) -> Iterator[None]:
    """Log heartbeat messages during long-running operations with no output."""
    stop_event = threading.Event()
    start_time = datetime.now()

    def heartbeat_thread() -> None:
        beat_count = 0
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            beat_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            log.info("heartbeat: %s still running (%.1fs elapsed, beat #%d)", operation, elapsed, beat_count)

    thread = threading.Thread(target=heartbeat_thread, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1.0)
        elapsed = (datetime.now() - start_time).total_seconds()
        log.info("heartbeat: %s completed (%.1fs total)", operation, elapsed)


def stream_output(stream: IO[str], prefix: str) -> None:
    """Stream output line by line, logging each line as it arrives."""
    for raw_line in stream:
        line = raw_line.rstrip("\n\r")
        if line:
            log.info("%s %s", prefix, line)


def run_streaming(cmd: list[str], operation: str, check: bool = True, env: dict[str, str] | None = None) -> int:
    """Run command with real-time streaming output.

    Streams stdout and stderr to the log as lines arrive.
    Uses heartbeat as fallback for periods with no output.
    """
    log.info(">>> %s", " ".join(cmd))
    start_time = datetime.now()

    merged_env = {**os.environ, **(env or {})}

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
        env=merged_env,
    )

    assert proc.stdout is not None

    # Stream output with heartbeat fallback
    last_output_time = datetime.now()
    heartbeat_count = 0

    while True:
        # Use a timeout so we can emit heartbeats during long silences
        import select

        ready, _, _ = select.select([proc.stdout], [], [], HEARTBEAT_INTERVAL_SECONDS)

        if ready:
            line = proc.stdout.readline()
            if not line:
                # EOF - process finished
                break
            line = line.rstrip("\n\r")
            if line:
                log.info("  | %s", line)
                last_output_time = datetime.now()
        else:
            # No output - emit heartbeat
            heartbeat_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            silence = (datetime.now() - last_output_time).total_seconds()
            log.info(
                "  ~ %s: waiting (%.1fs elapsed, %.1fs since last output, beat #%d)",
                operation,
                elapsed,
                silence,
                heartbeat_count,
            )

    proc.wait()
    elapsed = (datetime.now() - start_time).total_seconds()

    if proc.returncode == 0:
        log.info("<<< %s completed successfully (%.1fs)", operation, elapsed)
    else:
        log.error("<<< %s failed with code %d (%.1fs)", operation, proc.returncode, elapsed)
        if check:
            raise RuntimeError(f"{operation} failed with exit code {proc.returncode}")

    return proc.returncode


def which(cmd: str) -> str | None:
    """Find command in PATH."""
    result = subprocess.run(["which", cmd], capture_output=True, text=True, check=False)
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

    # Download with progress bar
    run_streaming(
        ["curl", "--progress-bar", "-L", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"],
        "downloading nix installer",
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
    # WORKAROUND:
    # Skip nix-env entirely. The installer already unpacked Nix to /nix/store.
    # We use the store path directly instead of relying on profiles.
    run_streaming(
        ["sh", "-x", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        "running nix installer",
        check=False,  # Installer may fail on nix-env step, that's OK
    )

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

    # Filter out tools that are already available
    missing_tools = [t for t in tools if not which(t)]
    if not missing_tools:
        log.info("All tools already available: %s", ", ".join(tools))
        return

    log.info("Installing tools: %s", ", ".join(missing_tools))

    # Install all missing tools in one command with verbose output
    # -v: verbose, --print-build-logs: show build output
    cmd = [str(nix_cmd), "profile", "install", "-v", "--print-build-logs"] + [f"nixpkgs#{t}" for t in missing_tools]

    run_streaming(cmd, f"installing {', '.join(missing_tools)}")

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
    if which("direnv"):
        for envrc in project_dir.rglob(".envrc"):
            log.info("Allowing direnv for: %s", envrc.parent)
            run_streaming(["direnv", "allow", str(envrc.parent)], f"direnv allow {envrc.parent.name}", check=False)

    # Persist environment with both store bin and profile bin
    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), nix_store_bin, project_dir)

    log.info("=" * 60)
    log.info("Session environment initialized:")
    for tool in ["nix", *TOOLS]:
        if path := which(tool):
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
