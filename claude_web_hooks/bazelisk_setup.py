"""Install Bazelisk for Bazel version management.

Bazelisk automatically downloads and runs the correct Bazel version
based on .bazelversion or USE_BAZEL_VERSION.

TODO: Eventually unify tool installation via direnv/devenv instead of
      manual downloads in session hooks.

IMPORTANT: This module must not import any non-stdlib packages.
"""

from __future__ import annotations

import logging
import platform
import stat
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

from claude_web_hooks.supervisor_setup import SUPERVISOR_CONF, SUPERVISOR_DIR, SUPERVISOR_SOCK

log = logging.getLogger(__name__)

BAZELISK_VERSION = "1.25.0"
# Private install location - we put wrapper in bin/, bazelisk in bazelisk
CACHE_DIR = Path.home() / ".cache" / "bazel-proxy"
BAZELISK_PATH = CACHE_DIR / "bazelisk"  # The actual bazelisk binary
WRAPPER_DIR = CACHE_DIR / "bin"  # Dir with wrapper, added to PATH
WRAPPER_PATH = WRAPPER_DIR / "bazel"  # The wrapper script


def get_bazelisk_url() -> str:
    """Get the appropriate Bazelisk download URL for this platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize architecture names
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")

    if system == "linux":
        binary = f"bazelisk-linux-{arch}"
    elif system == "darwin":
        binary = f"bazelisk-darwin-{arch}"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

    return f"https://github.com/bazelbuild/bazelisk/releases/download/v{BAZELISK_VERSION}/{binary}"


def install_bazelisk() -> Path:
    """Download bazelisk to private location, returning the binary path.

    Installs to ~/.cache/bazel-proxy/bazelisk (private, not on PATH).
    The wrapper script in ~/.cache/bazel-proxy/bin/bazel will call this.
    Skips download if already installed.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Check if already installed
    if BAZELISK_PATH.exists():
        result = subprocess.run([str(BAZELISK_PATH), "--version"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            log.info("Bazelisk already installed: %s", BAZELISK_PATH)
            return BAZELISK_PATH

    url = get_bazelisk_url()
    log.info("Downloading Bazelisk from %s", url)

    # Download with proxy support (urllib respects https_proxy env var)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            BAZELISK_PATH.write_bytes(response.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to download Bazelisk: {e}") from e

    # Make executable
    BAZELISK_PATH.chmod(BAZELISK_PATH.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log.info("Installed Bazelisk to %s", BAZELISK_PATH)

    return BAZELISK_PATH


def install_wrapper() -> Path:
    """Install wrapper script that sets proxy env vars before calling bazelisk.

    The wrapper is in ~/.cache/bazel-proxy/bin/bazel and calls the real
    bazelisk at ~/.cache/bazel-proxy/bazelisk.
    Also creates a bazelisk symlink for pre-commit hooks.
    Includes health checks for supervisor and proxy service.

    The wrapper reads configuration from environment variables (set via get_env_script).
    """
    WRAPPER_DIR.mkdir(parents=True, exist_ok=True)

    # Copy Python wrapper script as-is (no template substitution)
    wrapper_source = Path(__file__).parent / "bazel_wrapper.py"
    WRAPPER_PATH.write_text(wrapper_source.read_text())
    WRAPPER_PATH.chmod(0o755)
    log.info("Installed bazel wrapper at %s with health checks", WRAPPER_PATH)

    # Create bazelisk symlink for pre-commit hooks
    bazelisk_symlink = WRAPPER_DIR / "bazelisk"
    if bazelisk_symlink.exists() or bazelisk_symlink.is_symlink():
        bazelisk_symlink.unlink()
    bazelisk_symlink.symlink_to(WRAPPER_PATH)
    log.info("Created bazelisk symlink at %s", bazelisk_symlink)

    return WRAPPER_PATH


def get_env_script(
    proxy_port: int,
    repo_root: Path,
    hook_timestamp: datetime,
    combined_ca: Path | None = None,
    nix_profile_bin: Path | None = None,
) -> str:
    """Get bash script fragment to add wrapper dir to PATH and set config env vars.

    This should be appended to CLAUDE_ENV_FILE.

    Args:
        proxy_port: Port for the local Bazel proxy (required)
        repo_root: Path to the repository root for error messages (required)
        hook_timestamp: Session start hook timestamp (required)
        combined_ca: Path to combined CA bundle for Node.js (optional)
        nix_profile_bin: Path to nix profile bin directory (optional)
    """
    local_proxy = f"http://localhost:{proxy_port}"

    exports = {
        "PATH": f"{WRAPPER_DIR}:$PATH",
        "BAZELISK_PATH": str(BAZELISK_PATH),
        "BAZEL_SUPERVISOR_SOCK": str(SUPERVISOR_SOCK),
        "BAZEL_LOCAL_PROXY": local_proxy,
        "DUCKTAPE_REPO_ROOT": str(repo_root),
        "DUCKTAPE_SESSION_START_HOOK_TS": hook_timestamp.isoformat(),
    }

    if combined_ca:
        exports["NODE_EXTRA_CA_CERTS"] = str(combined_ca)

    lines = ["# Bazel wrapper (sets proxy for TLS-inspecting proxy)"]
    lines.append(f'[ -d "{WRAPPER_DIR}" ] && export PATH="{WRAPPER_DIR}:$PATH"')

    # Add nix to PATH first if provided
    if nix_profile_bin:
        lines.append(f'[ -d "{nix_profile_bin}" ] && export PATH="{nix_profile_bin}:$PATH"')

    for key, value in exports.items():
        if key != "PATH":  # PATH already handled with conditionals
            lines.append(f'export {key}="{value}"')

    return "\n".join(lines) + "\n"


def is_installed() -> bool:
    """Check if bazelisk is available."""
    return BAZELISK_PATH.exists()


def get_status() -> str:
    """Get status string for logging."""
    if WRAPPER_PATH.exists():
        # Get version from the actual bazelisk
        result = subprocess.run([str(BAZELISK_PATH), "version"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            # Extract first line (aspect or bazel version)
            version = result.stdout.split("\n")[0].strip()
            return f"{version} ({WRAPPER_PATH})"
    if BAZELISK_PATH.exists():
        return f"bazelisk at {BAZELISK_PATH} (no wrapper)"
    return "not installed"
