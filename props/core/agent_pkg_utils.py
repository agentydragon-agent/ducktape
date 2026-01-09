"""Agent package utilities for packing, unpacking, and validating packages.

This module provides:
- pack_agent_pkg: Pack a self-contained directory into tar archive
- unpack_agent_pkg: Extract tar archive to directory
- validate_packed_agent_pkg: Validate a packed archive

For repo-backed packages synced to DB, see db/sync/_sync.py which uses
MANIFEST files and git archive for clean packing.

For agent-created packages:
- Must be self-contained (no external symlinks)
- Packed directly from directory contents using pack_agent_pkg()
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

# Required files in agent package tar (build context)
DOCKERFILE_FILE = "Dockerfile"
MANIFEST_FILE = "MANIFEST"


class AgentPkgValidationError(Exception):
    """Raised when agent package validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        error_list = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"Invalid agent package:\n{error_list}")


def validate_packed_agent_pkg(archive: bytes) -> None:
    """Validate a packed archive has required files for building.

    Only validates Dockerfile presence. /init is validated in the built
    image via agent_pkg.builder.validate_image().

    Raises:
        AgentPkgValidationError: If Dockerfile is missing.
    """
    buffer = io.BytesIO(archive)

    with tarfile.open(fileobj=buffer, mode="r") as tar:
        if DOCKERFILE_FILE not in tar.getnames():
            raise AgentPkgValidationError([f"Missing required file: {DOCKERFILE_FILE}"])


def pack_agent_pkg(pkg_dir: Path) -> bytes:
    """Pack a self-contained directory into tar archive.

    For agent-created packages only. Packs directory contents directly.
    No external symlinks allowed.

    For repo-backed packages, use the sync process which handles
    MANIFEST files and git archive.

    Raises:
        NotADirectoryError: If pkg_dir is not a directory.
        ValueError: If external symlinks are found.
        AgentPkgValidationError: If validation fails.
    """
    if not pkg_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {pkg_dir}")

    files: dict[str, Path] = {}
    _collect_files_from_dir(pkg_dir, pkg_dir, files)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel in sorted(files.keys()):
            path = files[rel]
            tar.add(path, arcname=rel)

    archive = buffer.getvalue()
    validate_packed_agent_pkg(archive)
    return archive


def _is_external_symlink(path: Path, pkg_dir: Path) -> bool:
    """Check if a path is a symlink pointing outside the package directory."""
    if not path.is_symlink():
        return False
    resolved = path.resolve()
    pkg_resolved = pkg_dir.resolve()
    return not str(resolved).startswith(str(pkg_resolved) + "/") and resolved != pkg_resolved


def _collect_files_from_dir(source_dir: Path, pkg_dir: Path, files: dict[str, Path], *, rel_prefix: str = "") -> None:
    """Collect files from a directory. No external symlinks allowed."""
    for path in sorted(source_dir.iterdir()):
        name = path.name
        if name == "__pycache__":
            continue
        rel_path = f"{rel_prefix}{name}" if rel_prefix else name

        if _is_external_symlink(path, pkg_dir):
            raise ValueError(
                f"External symlink not allowed: {rel_path} -> {path.resolve()}. "
                f"Agent-created packages must be self-contained."
            )

        if path.is_dir():
            _collect_files_from_dir(path, pkg_dir, files, rel_prefix=f"{rel_path}/")
            continue

        if path.is_file():
            if rel_path.endswith(".pyc"):
                continue
            files[rel_path] = path


def unpack_agent_pkg(archive: bytes, target_dir: Path) -> None:
    """Unpack tar archive to target directory.

    Validates the archive before unpacking.

    Raises:
        AgentPkgValidationError: If archive is invalid.
    """
    validate_packed_agent_pkg(archive)
    target_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        tar.extractall(target_dir)
