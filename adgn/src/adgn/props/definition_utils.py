"""Agent definition utilities for packing, unpacking, and validating definitions.

This module is intentionally lightweight (no heavy imports) to avoid circular
imports. It provides:
- validate_definition: Check definition structure (AGENT.md, init script)
- pack_definition: Pack directory into tar archive
- unpack_definition: Extract tar archive to directory

These functions are used by:
- db/sync/_sync.py: For syncing repo-backed definitions
- cli/cmd_agent_definition.py: For CLI commands
- prompt_optimize/prompt_optimizer.py: For agent-created definitions
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import tarfile


def validate_definition(definition_dir: Path) -> list[str]:
    """Validate agent definition structure, return list of errors.

    Checks that required files exist in the directory before packing.
    For repo-backed definitions with symlinks, use pack_definition() followed
    by validate_packed_definition() to validate the resolved archive.

    Args:
        definition_dir: Agent definition directory to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # AGENT.md required
    agent_md = definition_dir / "AGENT.md"
    if not agent_md.exists():
        errors.append("Missing required file: AGENT.md")

    # init required and must be executable
    init_script = definition_dir / "init"
    if not init_script.exists():
        errors.append("Missing required file: init")
    elif not os.access(init_script, os.X_OK):
        errors.append("init script must be executable (chmod +x)")

    return errors


def _is_external_symlink(path: Path, definition_dir: Path) -> bool:
    """Check if a path is a symlink pointing outside the definition directory."""
    if not path.is_symlink():
        return False
    resolved = path.resolve()
    try:
        resolved.relative_to(definition_dir.resolve())
        return False  # Inside definition
    except ValueError:
        return True  # Outside definition


def _collect_files_from_dir(
    source_dir: Path,
    definition_dir: Path,
    files: dict[str, Path],
    resolve_external_symlinks: bool,
    *,
    rel_prefix: str = "",
) -> None:
    """Collect files from a directory, optionally resolving external symlinks.

    Handles both file and directory symlinks. For external directory symlinks,
    recursively includes all files from the symlink target.

    Args:
        source_dir: Directory to collect files from
        definition_dir: The main definition directory (for determining if symlinks are "external")
        files: Dict to update with relative path -> source path mappings
        resolve_external_symlinks: If True, resolve symlinks pointing outside definition_dir.
            If False, raises ValueError on external symlinks (security mode).
        rel_prefix: Relative path prefix from root (for recursion tracking)

    Raises:
        ValueError: If resolve_external_symlinks=False and an external symlink is found
    """
    for path in sorted(source_dir.iterdir()):
        name = path.name
        if name == "__pycache__":
            # TODO: centralize pack/sync ignore rules instead of ad-hoc skips.
            continue
        rel_path = f"{rel_prefix}{name}" if rel_prefix else name

        # Check for external symlinks
        is_external = _is_external_symlink(path, definition_dir)

        if is_external and not resolve_external_symlinks:
            # Security mode: reject external symlinks entirely
            raise ValueError(
                f"External symlink not allowed: {rel_path} -> {path.resolve()}. "
                f"Agent-created definitions must be self-contained."
            )

        # Handle directory symlinks pointing outside
        if path.is_symlink() and path.is_dir() and is_external:
            # External directory symlink - recursively add all its contents
            resolved = path.resolve()
            for subpath in sorted(resolved.rglob("*")):
                if subpath.is_file():
                    rel = f"{rel_path}/{subpath.relative_to(resolved)}"
                    files[rel] = subpath
            continue

        # Regular directory (or internal symlink dir) - recurse
        if path.is_dir():
            _collect_files_from_dir(path, definition_dir, files, resolve_external_symlinks, rel_prefix=f"{rel_path}/")
            continue

        # Handle files
        if path.is_file():
            if rel_path.endswith(".pyc"):
                continue
            # Check if it's a symlink pointing outside the definition directory
            if is_external:
                # Outside definition - use resolved path (will copy content, not symlink)
                files[rel_path] = path.resolve()
            else:
                files[rel_path] = path


def pack_definition(definition_dir: Path, *, resolve_symlinks: bool = True) -> bytes:
    """Pack directory into uncompressed tar archive.

    Preserves file permissions (especially executable flag for init script).

    **Symlink handling (resolve_symlinks=True, default):**
    Symlinks pointing outside the definition directory are resolved - the symlink
    target's content is included rather than a broken symlink. This allows repo-backed
    agent definitions to reference shared files via symlinks (e.g., `dead_code/bin -> ../critic/bin`).

    **Security (resolve_symlinks=False):**
    For agent-created definitions (e.g., by prompt optimizer), use resolve_symlinks=False
    to prevent directory escape attacks. External symlinks will be rejected with an error.

    Args:
        definition_dir: Agent definition directory to pack
        resolve_symlinks: If True, resolve external symlinks. If False, reject them.

    Returns:
        Bytes of tar archive

    Raises:
        ValueError: If resolve_symlinks=False and external symlinks are found
    """
    files: dict[str, Path] = {}
    _collect_files_from_dir(definition_dir, definition_dir, files, resolve_external_symlinks=resolve_symlinks)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for rel in sorted(files.keys()):
            path = files[rel]
            tar.add(path, arcname=rel)
    return buffer.getvalue()


def unpack_definition(archive: bytes, target_dir: Path) -> None:
    """Unpack tar archive to target directory.

    Args:
        archive: Bytes of tar archive
        target_dir: Directory to extract to (created if needed)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        tar.extractall(target_dir)


def validate_packed_definition(archive: bytes) -> list[str]:
    """Validate a packed archive has required files.

    Validates the packed archive after symlink resolution. For repo-backed
    definitions with symlinks (e.g., `dead_code/init -> ../critic/init`),
    this checks the resolved content is valid.

    Args:
        archive: Tar archive bytes to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    buffer = io.BytesIO(archive)

    with tarfile.open(fileobj=buffer, mode="r") as tar:
        names = tar.getnames()

        # AGENT.md required
        if "AGENT.md" not in names:
            errors.append("Missing required file: AGENT.md")

        # init required and must be executable
        if "init" not in names:
            errors.append("Missing required file: init")
        else:
            member = tar.getmember("init")
            # Check if executable bit is set (mode & 0o111)
            if not (member.mode & 0o111):
                errors.append("init script must be executable (chmod +x)")

    return errors
