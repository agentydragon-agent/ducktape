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


def _find_current_worktree_info(daemon, current_path: Path, worktree_infos: list):
    if current_path.is_relative_to(daemon.config.main_repo_resolved):
        for info in worktree_infos:
            if info.is_main:
                relative_path = str(current_path.relative_to(daemon.config.main_repo_resolved))
                return info, relative_path
    for info in worktree_infos:
        if not info.is_main and current_path.is_relative_to(info.path):
            relative_path = str(current_path.relative_to(info.path))
            return info, relative_path
    return None, None


def _find_target_worktree(daemon, worktree_name: str | None, current_path: Path, worktree_infos: list):
    if worktree_name:
        for info in worktree_infos:
            if (info.is_main and worktree_name == MAIN_WORKTREE_DISPLAY_NAME) or (
                not info.is_main and info.path.name == worktree_name
            ):
                return info, None
        raise ValueError(f"Worktree '{worktree_name}' not found")
    found_worktree, relative_path = _find_current_worktree_info(daemon, current_path, worktree_infos)
    if not found_worktree:
        raise ValueError(f"Current path {current_path} is not in a managed worktree")
    return found_worktree, relative_path


def _resolve_path_spec(path_spec: str, target_path: Path, current_relative_path: str | None, is_current_worktree: bool) -> Path:
    if path_spec.startswith("/"):
        return target_path / path_spec.lstrip("/")
    if path_spec.startswith("./"):
        if not is_current_worktree:
            raise ValueError("Cannot use relative path for different worktree")
        current_dir = target_path / current_relative_path if current_relative_path else target_path
        return (current_dir / path_spec).resolve()
    return target_path / path_spec


from ..registry import register


@register("worktree_resolve_path")
def handle_resolve_path(daemon, request: Request, start_time: float) -> Response:
    params = WorktreeResolvePathParams.model_validate(request.params)
    current_path = Path(params.current_path)
    worktree_infos = daemon.git_manager.list_worktrees()
    target_worktree, current_relative_path = _find_target_worktree(daemon, params.worktree_name, current_path, worktree_infos)
    resolved_path = _resolve_path_spec(params.path_spec, target_worktree.path, current_relative_path, params.worktree_name is None)
    result = WorktreeResolvePathResult(absolute_path=str(resolved_path))
    return Response(result=result, id=request.id)


@register("worktree_teleport_target")
def handle_teleport_target(daemon, request: Request, start_time: float) -> Response:
    params = WorktreeTeleportTargetParams.model_validate(request.params)
    current_path = Path(params.current_path)
    worktree_infos = daemon.git_manager.list_worktrees()
    target_worktree = None
    for info in worktree_infos:
        if (info.is_main and params.target_name == MAIN_WORKTREE_DISPLAY_NAME) or (
            not info.is_main and info.path.name == params.target_name
        ):
            target_worktree = info
            break
    if not target_worktree:
        result = TeleportDoesNotExist(type="does_not_exist", name=params.target_name)
        return Response(result=result, id=request.id)
    current_worktree, relative_path = _find_current_worktree_info(daemon, current_path, worktree_infos)
    cd_path = str(target_worktree.path) if not relative_path or relative_path == "." else (
        str(target_worktree.path / relative_path) if (target_worktree.path / relative_path).exists() and (target_worktree.path / relative_path).is_dir() else str(target_worktree.path)
    )
    result = TeleportCdThere(type="cd_there", cd_path=cd_path)
    return Response(result=result, id=request.id)
