#!/usr/bin/env python3
"""Session start hook for Claude Code web: sets up nix, direnv, devenv, uv."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("/tmp/session-start-direnv.log")
TOOLS = ["direnv", "devenv", "uv"]

# Configure logging to both stdout and file
logging.basicConfig(
    level=logging.INFO,
    format="[session-start-direnv] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
log = logging.getLogger(__name__)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run command, logging output."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            log.info("  %s", line)
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            log.info("  %s", line)
    if check and result.returncode != 0:
        log.warning("Command failed (exit %d): %s", result.returncode, " ".join(cmd))
    return result


def which(cmd: str) -> str | None:
    """Find command in PATH, return path or None."""
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
    paths_to_add = []

    nix_bin = find_nix_bin()
    if nix_bin:
        paths_to_add.append(str(nix_bin))

    nix_profile_bin = Path.home() / ".nix-profile" / "bin"
    if nix_profile_bin.exists():
        paths_to_add.append(str(nix_profile_bin))

    if paths_to_add:
        os.environ["PATH"] = ":".join(paths_to_add) + ":" + os.environ.get("PATH", "")
        log.info("Added to PATH: %s", ", ".join(paths_to_add))


def install_nix(project_dir: Path) -> bool:
    """Install nix if not present. Returns True if nix is available after."""
    if which("nix"):
        log.info("nix already available")
        return True

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    if nix_conf.exists():
        os.environ["NIX_USER_CONF_FILES"] = str(nix_conf)
        log.info("Using nix.conf: %s", nix_conf)

    log.info("Installing nix...")

    subprocess.run(
        ["curl", "-sL", "https://nixos.org/nix/install", "-o", "/tmp/nix-install.sh"],
        check=True,
    )
    subprocess.run(
        ["sh", "/tmp/nix-install.sh", "--no-daemon", "--no-channel-add", "--no-modify-profile"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )

    # Manual profile setup (workaround for gVisor PTY bug breaking nix-env)
    nix_profile = Path.home() / ".nix-profile"
    if not (nix_profile / "bin" / "nix").exists():
        nix_bin = find_nix_bin()
        if nix_bin:
            nix_pkg = nix_bin.parent
            profiles_dir = Path("/nix/var/nix/profiles/per-user/root")
            profiles_dir.mkdir(parents=True, exist_ok=True)
            profile_link = profiles_dir / "profile"
            profile_link.unlink(missing_ok=True)
            profile_link.symlink_to(nix_pkg)
            nix_profile.unlink(missing_ok=True)
            nix_profile.symlink_to(profile_link)
            log.info("Created manual profile link: %s", nix_pkg)

    setup_nix_path()
    return which("nix") is not None


def install_tool(tool: str) -> bool:
    """Install a tool via nix profile. Returns True on success."""
    if which(tool):
        log.info("%s already available", tool)
        return True

    log.info("Installing %s...", tool)
    result = run(["nix", "profile", "install", f"nixpkgs#{tool}"], check=False)

    if result.returncode == 0:
        log.info("%s installed successfully", tool)
        return True
    else:
        log.warning("%s installation failed (exit %d)", tool, result.returncode)
        return False


def allow_envrc_files(project_dir: Path) -> None:
    """Allow all .envrc files in the project."""
    if not which("direnv"):
        return
    for envrc in project_dir.rglob(".envrc"):
        subprocess.run(["direnv", "allow", str(envrc.parent)], capture_output=True)


def persist_environment(env_file: str | None, project_dir: Path) -> None:
    """Write environment to CLAUDE_ENV_FILE for persistence."""
    if not env_file:
        log.warning("CLAUDE_ENV_FILE is empty, PATH changes will not persist")
        return

    nix_conf = project_dir / ".claude" / "claude-code-web" / "nix.conf"
    nix_bin = find_nix_bin()

    content = f"""# Nix environment (added by session-start-direnv.py)
export NIX_USER_CONF_FILES="{nix_conf}"
[ -d "{nix_bin}" ] && export PATH="{nix_bin}:$PATH"
[ -d ~/.nix-profile/bin ] && export PATH="$HOME/.nix-profile/bin:$PATH"
"""
    with open(env_file, "a") as f:
        f.write(content)
    log.info("Wrote environment to CLAUDE_ENV_FILE=%s", env_file)


def main() -> int:
    log.info("Starting hook at %s", datetime.now().isoformat())
    log.info("Environment: %s", json.dumps(dict(os.environ), sort_keys=True))

    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        log.info("Not remote environment, skipping")
        return 0

    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir_str:
        log.error("CLAUDE_PROJECT_DIR not set, cannot proceed")
        return 1
    project_dir = Path(project_dir_str)

    log.info("Setting up dev environment...")

    if not install_nix(project_dir):
        log.error("Failed to install nix")
        return 1

    for tool in TOOLS:
        install_tool(tool)

    allow_envrc_files(project_dir)
    persist_environment(os.environ.get("CLAUDE_ENV_FILE"), project_dir)

    # Report status
    log.info("Session environment initialized:")
    for tool in ["nix"] + TOOLS:
        path = which(tool)
        if path:
            result = subprocess.run([tool, "--version"], capture_output=True, text=True)
            version = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "unknown"
            log.info("  %s: %s", tool, version)
        else:
            log.info("  %s: N/A", tool)

    log.info("Setup complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
