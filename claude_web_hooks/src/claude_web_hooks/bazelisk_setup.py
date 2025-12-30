"""Install Bazelisk for Bazel version management.

Bazelisk automatically downloads and runs the correct Bazel version
based on .bazelversion or USE_BAZEL_VERSION.

TODO: Eventually unify tool installation via direnv/devenv instead of
      manual downloads in session hooks.

IMPORTANT: This module must not import any non-stdlib packages.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import platform
import shutil
import stat
import urllib.request

log = logging.getLogger(__name__)

BAZELISK_VERSION = "1.25.0"
INSTALL_DIR = Path.home() / ".local" / "bin"


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
    """Download and install Bazelisk, returning the install path.

    Installs to ~/.local/bin/bazel so it's available as 'bazel'.
    Skips download if already installed at correct version.
    """
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    bazel_path = INSTALL_DIR / "bazel"

    # Check if already installed
    if bazel_path.exists():
        # Verify it's bazelisk by checking --version output
        import subprocess

        result = subprocess.run([str(bazel_path), "--version"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and "bazelisk" in result.stdout.lower():
            log.info("Bazelisk already installed: %s", bazel_path)
            return bazel_path
        # Not bazelisk or broken, remove and reinstall
        bazel_path.unlink()

    url = get_bazelisk_url()
    log.info("Downloading Bazelisk from %s", url)

    # Download with proxy support (urllib respects https_proxy env var)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            bazel_path.write_bytes(response.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to download Bazelisk: {e}") from e

    # Make executable
    bazel_path.chmod(bazel_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log.info("Installed Bazelisk to %s", bazel_path)

    # Ensure ~/.local/bin is in PATH
    ensure_path()

    return bazel_path


def ensure_path() -> None:
    """Ensure ~/.local/bin is in PATH for this session."""
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    install_str = str(INSTALL_DIR)
    if install_str not in path_dirs:
        os.environ["PATH"] = install_str + os.pathsep + os.environ.get("PATH", "")
        log.info("Added %s to PATH", INSTALL_DIR)


def is_installed() -> bool:
    """Check if bazelisk is available."""
    return shutil.which("bazel") is not None


def get_status() -> str:
    """Get status string for logging."""
    bazel = shutil.which("bazel")
    if bazel:
        return f"installed ({bazel})"
    return "not installed"
