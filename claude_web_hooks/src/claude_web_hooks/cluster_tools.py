"""Install cluster tools for pre-commit hooks.

Tools installed:
- opentofu: Terraform alternative (for terraform_fmt, terraform_validate hooks)
- tflint: Terraform linter (for terraform_tflint hook)
- flux: GitOps toolkit (for flux-build-dry-run hook)
- kustomize: Kubernetes configuration (for kustomize-dry-run hook)

These are only installed if the cluster/ directory exists in the project.
Binary downloads are used instead of nix because nix setup is too slow
and times out in the Claude Code web environment.

IMPORTANT: This module must not import any non-stdlib packages.
"""

from __future__ import annotations

import logging
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

# Tool versions - keep in sync with .envrc and CI workflow
OPENTOFU_VERSION = "1.9.0"
TFLINT_VERSION = "0.53.0"
FLUX_VERSION = "2.4.0"
KUSTOMIZE_VERSION = "5.5.0"

# Install location
TOOLS_DIR = Path.home() / ".local" / "bin"


def _get_arch() -> str:
    """Get normalized architecture name."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(f"Unsupported architecture: {machine}")


def _download_and_extract(url: str, binary_name: str, dest_path: Path) -> bool:
    """Download archive, extract binary, and install to dest_path.

    Supports .tar.gz and .zip archives.
    Returns True on success, False on failure.
    """
    log.info("Downloading %s from %s", binary_name, url)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Download
            archive_path = tmppath / "archive"
            with urllib.request.urlopen(url, timeout=120) as response:
                archive_path.write_bytes(response.read())

            # Extract
            extract_dir = tmppath / "extracted"
            extract_dir.mkdir()

            if url.endswith((".tar.gz", ".tgz")):
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(extract_dir)
            elif url.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extract_dir)
            else:
                log.error("Unknown archive format: %s", url)
                return False

            # Find the binary (might be in root or a subdirectory)
            binary_path = None
            for path in extract_dir.rglob(binary_name):
                if path.is_file():
                    binary_path = path
                    break

            if not binary_path:
                # Sometimes the binary has a different name in archive
                # Try finding any executable
                for path in extract_dir.iterdir():
                    if path.is_file() and not path.suffix:
                        binary_path = path
                        break

            if not binary_path:
                log.error("Could not find %s in archive", binary_name)
                return False

            # Install
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary_path, dest_path)
            dest_path.chmod(dest_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            log.info("Installed %s to %s", binary_name, dest_path)
            return True

    except urllib.error.URLError as e:
        log.error("Failed to download %s: %s", binary_name, e)
        return False
    except (tarfile.TarError, zipfile.BadZipFile) as e:
        log.error("Failed to extract %s: %s", binary_name, e)
        return False


def _is_installed(binary_name: str, version_flag: str = "--version") -> bool:
    """Check if a tool is already installed and working."""
    binary_path = TOOLS_DIR / binary_name
    # Check if binary exists in our tools dir or is in PATH
    if not binary_path.exists() and shutil.which(binary_name) is None:
        return False
    try:
        result = subprocess.run([binary_name, version_flag], capture_output=True, text=True, check=False, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def install_opentofu(version: str = OPENTOFU_VERSION) -> bool:
    """Download and install OpenTofu binary."""
    if _is_installed("tofu"):
        log.info("OpenTofu already installed")
        return True

    arch = _get_arch()
    url = f"https://github.com/opentofu/opentofu/releases/download/v{version}/tofu_{version}_linux_{arch}.zip"
    return _download_and_extract(url, "tofu", TOOLS_DIR / "tofu")


def install_tflint(version: str = TFLINT_VERSION) -> bool:
    """Download and install tflint binary."""
    if _is_installed("tflint"):
        log.info("tflint already installed")
        return True

    arch = _get_arch()
    url = f"https://github.com/terraform-linters/tflint/releases/download/v{version}/tflint_linux_{arch}.zip"
    return _download_and_extract(url, "tflint", TOOLS_DIR / "tflint")


def install_flux(version: str = FLUX_VERSION) -> bool:
    """Download and install Flux CLI binary."""
    if _is_installed("flux"):
        log.info("Flux already installed")
        return True

    arch = _get_arch()
    url = f"https://github.com/fluxcd/flux2/releases/download/v{version}/flux_{version}_linux_{arch}.tar.gz"
    return _download_and_extract(url, "flux", TOOLS_DIR / "flux")


def install_kustomize(version: str = KUSTOMIZE_VERSION) -> bool:
    """Download and install kustomize binary."""
    if _is_installed("kustomize"):
        log.info("kustomize already installed")
        return True

    arch = _get_arch()
    url = f"https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv{version}/kustomize_v{version}_linux_{arch}.tar.gz"
    return _download_and_extract(url, "kustomize", TOOLS_DIR / "kustomize")


def install_all() -> dict[str, bool]:
    """Install all cluster tools.

    Returns dict mapping tool name to success status.
    """
    return {
        "opentofu": install_opentofu(),
        "tflint": install_tflint(),
        "flux": install_flux(),
        "kustomize": install_kustomize(),
    }


def get_status() -> str:
    """Get status string for logging."""
    installed = []
    missing = []

    for tool in ["tofu", "tflint", "flux", "kustomize"]:
        if _is_installed(tool):
            installed.append(tool)
        else:
            missing.append(tool)

    if not missing:
        return f"all installed ({', '.join(installed)})"
    if not installed:
        return "none installed"
    return f"partial ({', '.join(installed)}; missing: {', '.join(missing)})"
