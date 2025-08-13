from __future__ import annotations

from pathlib import Path

from ...shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from ...shared.protocol import (
    Request,
    Response,
    TeleportCdThere,
    TeleportDoesNotExist,
    WorktreeResolvePathParams,
    WorktreeResolvePathResult,
    WorktreeTeleportTargetParams,
)
from ..rpc import rpc, Context
from ..worktree_index import WorktreeIndex


def _find_target_worktree(
    daemon, worktree_name: str | None, current_path: Path
):
    if not daemon.worktree_index:
        raise ValueError("Worktree index unavailable")
    if worktree_name == MAIN_WORKTREE_DISPLAY_NAME and daemon.worktree_index.main:
        return daemon.worktree_index.main, None
    resolved = daemon.worktree_index.resolve_target(worktree_name, current_path)
    if not resolved:
        raise ValueError(f"Worktree '{worktree_name or current_path}' not found")
    return resolved


def _resolve_path_spec(
    path_spec: str,
    target_path: Path,
    current_relative_path: str | None,
    is_current_worktree: bool,
) -> Path:
    if path_spec.startswith("/"):
        return target_path / path_spec.lstrip("/")
    if path_spec.startswith("./"):
        if not is_current_worktree:
            raise ValueError("Cannot use relative path for different worktree")
        current_dir = (
            target_path / current_relative_path
            if current_relative_path
            else target_path
        )
        return (current_dir / path_spec).resolve()
    return target_path / path_spec


@rpc.method("worktree_resolve_path", params=WorktreeResolvePathParams)
async def handle_resolve_path(ctx: Context, params: WorktreeResolvePathParams) -> WorktreeResolvePathResult:
    current_path = Path(params.current_path)
    if not ctx.daemon.worktree_index:
        ctx.daemon.worktree_index = WorktreeIndex.build(ctx.daemon.known_worktrees.values(), ctx.daemon.config.main_repo)
    target_worktree, current_relative_path = _find_target_worktree(
        ctx.daemon, params.worktree_name, current_path
    )
    resolved_path = _resolve_path_spec(
        params.path_spec,
        target_worktree.path,
        current_relative_path,
        params.worktree_name is None,
    )
    return WorktreeResolvePathResult(absolute_path=str(resolved_path))


@rpc.method("worktree_teleport_target", params=WorktreeTeleportTargetParams)
async def handle_teleport_target(ctx: Context, params: WorktreeTeleportTargetParams) -> TeleportCdThere | TeleportDoesNotExist:
    current_path = Path(params.current_path)
    if not ctx.daemon.worktree_index:
        ctx.daemon.worktree_index = WorktreeIndex.build(ctx.daemon.known_worktrees.values(), ctx.daemon.config.main_repo)
    idx = ctx.daemon.worktree_index
    if not idx:
        return TeleportDoesNotExist(type="does_not_exist", name=params.target_name)
    if params.target_name == MAIN_WORKTREE_DISPLAY_NAME and idx.main:
        target_wt = idx.main
    else:
        target_wt = idx.get_by_name(params.target_name)
    if not target_wt:
        return TeleportDoesNotExist(type="does_not_exist", name=params.target_name)
    resolved = idx.resolve_target(None, current_path)
    relative_path = resolved[1] if resolved else None
    cd_path = (
        target_wt.path
        if not relative_path or relative_path == "."
        else (
            target_wt.path / relative_path
            if (target_wt.path / relative_path).exists()
            and (target_wt.path / relative_path).is_dir()
            else target_wt.path
        )
    )
    return TeleportCdThere(type="cd_there", cd_path=str(cd_path))
