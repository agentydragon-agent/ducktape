"""Direct worktree utility functions for CLI handlers."""

import asyncio
import shlex
import uuid
from pathlib import Path

from wt.shared.error_handling import validate_worktree_name
from wt.shared.protocol import (
    Request,
    Response,
    WorktreeResolvePathParams,
    WorktreeResolvePathResult,
)

from .shell_utils import emit_command
from .wt_client import WtClient

# GitInterface no longer needed - using RPC calls instead


async def get_worktree_path(config, name: str) -> Path:
    """Get path for a worktree by name via server."""
    client = WtClient(config)
    res = await client.get_worktree_by_name(name)
    if not res.exists or not res.absolute_path:
        raise RuntimeError(f"Worktree '{name}' not found")
    return Path(res.absolute_path)


async def require_worktree_exists(config, name: str) -> Path:
    """Require that a worktree exists and return its path (server-resolved)."""
    return await get_worktree_path(config, name)


def get_current_worktree_info(config) -> tuple[Path | None, str | None]:
    """Get current worktree information."""
    cwd = Path.cwd()

    # Prefer detecting managed worktrees first (they live under worktrees dir)
    worktrees_dir = config.worktrees_dir_resolved
    if cwd.is_relative_to(worktrees_dir):
        for parent in [cwd, *list(cwd.parents)]:
            if parent.parent == worktrees_dir:
                try:
                    rel_path = cwd.relative_to(parent)
                    return parent, str(rel_path) if str(rel_path) != "." else None
                except ValueError:
                    return parent, None

    # Otherwise, check if we're in the main repo
    main_repo = config.main_repo_resolved
    if cwd.is_relative_to(main_repo):
        if cwd == main_repo:
            return main_repo, None
        try:
            rel_path = cwd.relative_to(main_repo)
            return main_repo, str(rel_path)
        except ValueError:
            pass

    return None, None


async def resolve_path(config, worktree_name: str | None, path_spec: str) -> Path:
    """Resolve a path specification within a worktree via server RPC."""
    client = WtClient(config)
    params = WorktreeResolvePathParams(
        worktree_name=worktree_name,
        path_spec=path_spec,
        current_path=str(Path.cwd()),
    )
    req = Request(method="worktree_resolve_path", params=params.model_dump(), id=uuid.uuid4())
    reader, writer = await asyncio.open_unix_connection(config.daemon_socket_file)
    writer.write(req.model_dump_json().encode())
    writer.write(b"\n")
    await writer.drain()
    resp = await reader.readline()
    writer.close()
    await writer.wait_closed()
    res = Response.model_validate_json(resp.decode())
    out = WorktreeResolvePathResult.model_validate(res.result)
    return Path(out.absolute_path)


def emit_cd_command(dest_repo: Path, config) -> None:
    """Emit a cd command for shell execution."""
    # Try to preserve relative path when switching between worktrees
    current_wt, rel_path = get_current_worktree_info(config)

    if rel_path and current_wt:
        target_subpath = dest_repo / rel_path
        dest_path = target_subpath if target_subpath.exists() and target_subpath.is_dir() else dest_repo
    else:
        dest_path = dest_repo

    emit_command(f"cd {shlex.quote(str(dest_path))}")


async def create_worktree(
    config,
    name: str,
    source_worktree: Path | None = None,
    from_default: bool = True,
) -> Path:
    """Create a new worktree via RPC."""
    validate_worktree_name(name)

    # Create daemon client
    daemon_client = WtClient(config)

    if source_worktree:
        identify_result = await daemon_client.identify_worktree(str(source_worktree))
        result = await daemon_client.create_worktree(name, source_wtid=identify_result.wtid)
        return Path(result.absolute_path)
    result = await daemon_client.create_worktree(name)
    return Path(result.absolute_path)


async def remove_worktree(config, name: str, force: bool = False) -> None:
    """Remove a worktree via RPC."""
    daemon_client = WtClient(config)

    # Get WorktreeID from server by listing all worktrees and finding the match
    worktree_list = await daemon_client.list_worktrees()

    # Find the worktree by name
    target_wtid = None
    for worktree in worktree_list.worktrees:
        if worktree.name == name:
            target_wtid = worktree.wtid
            break

    if target_wtid is None:
        raise RuntimeError(f"Worktree '{name}' not found")

    # Delete via RPC using server-provided WorktreeID
    result = await daemon_client.delete_worktree(target_wtid)

    if not result.success:
        raise RuntimeError(f"Failed to remove worktree '{name}'")
