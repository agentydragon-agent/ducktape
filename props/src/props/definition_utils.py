"""Agent definition utilities for packing, unpacking, and validating definitions.

This module provides:
- pack_definition: Pack a self-contained directory into tar archive
- unpack_definition: Extract tar archive to directory
- validate_packed_definition: Validate a packed archive

For repo-backed definitions synced to DB, see db/sync/_sync.py which uses
MANIFEST files and git archive for clean packing.

For agent-created definitions:
- Must be self-contained (no external symlinks)
- Packed directly from directory contents using pack_definition()
"""

from __future__ import annotations

import io
from pathlib import Path
import tarfile

# Required files in agent definition tar (build context)
DOCKERFILE_FILE = "Dockerfile"
MANIFEST_FILE = "MANIFEST"


class DefinitionValidationError(Exception):
    """Raised when agent definition validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        error_list = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"Invalid agent definition:\n{error_list}")


def validate_packed_definition(archive: bytes) -> None:
    """Validate a packed archive has required files for building.

    Only validates Dockerfile presence. AGENT.md and init are validated
    in the built image via definition_builder.validate_image().

    Raises:
        DefinitionValidationError: If Dockerfile is missing.
    """
    buffer = io.BytesIO(archive)

    with tarfile.open(fileobj=buffer, mode="r") as tar:
        if DOCKERFILE_FILE not in tar.getnames():
            raise DefinitionValidationError([f"Missing required file: {DOCKERFILE_FILE}"])


def pack_definition(definition_dir: Path) -> bytes:
    """Pack a self-contained directory into tar archive.

    For agent-created definitions only. Packs directory contents directly.
    No external symlinks allowed.

    For repo-backed definitions, use the sync process which handles
    MANIFEST files and git archive.

    Raises:
        NotADirectoryError: If definition_dir is not a directory.
        ValueError: If external symlinks are found.
        DefinitionValidationError: If validation fails.
    """
    if not definition_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {definition_dir}")

    files: dict[str, Path] = {}
    _collect_files_from_dir(definition_dir, definition_dir, files)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel in sorted(files.keys()):
            path = files[rel]
            tar.add(path, arcname=rel)

    archive = buffer.getvalue()
    validate_packed_definition(archive)
    return archive


def _is_external_symlink(path: Path, definition_dir: Path) -> bool:
    """Check if a path is a symlink pointing outside the definition directory."""
    if not path.is_symlink():
        return False
    resolved = path.resolve()
    definition_resolved = definition_dir.resolve()
    return not str(resolved).startswith(str(definition_resolved) + "/") and resolved != definition_resolved


def _collect_files_from_dir(
    source_dir: Path, definition_dir: Path, files: dict[str, Path], *, rel_prefix: str = ""
) -> None:
    """Collect files from a directory. No external symlinks allowed."""
    for path in sorted(source_dir.iterdir()):
        name = path.name
        if name == "__pycache__":
            continue
        rel_path = f"{rel_prefix}{name}" if rel_prefix else name

        if _is_external_symlink(path, definition_dir):
            raise ValueError(
                f"External symlink not allowed: {rel_path} -> {path.resolve()}. "
                f"Agent-created definitions must be self-contained."
            )

        if path.is_dir():
            _collect_files_from_dir(path, definition_dir, files, rel_prefix=f"{rel_path}/")
            continue

        if path.is_file():
            if rel_path.endswith(".pyc"):
                continue
            files[rel_path] = path


def unpack_definition(archive: bytes, target_dir: Path) -> None:
    """Unpack tar archive to target directory.

    Validates the archive before unpacking.

    Raises:
        DefinitionValidationError: If archive is invalid.
    """
    validate_packed_definition(archive)
    target_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        tar.extractall(target_dir)
