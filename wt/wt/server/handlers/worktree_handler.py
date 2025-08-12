from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ...shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from ...shared.protocol import (
    Request,
    Response,
    WorktreeCreateParams,
    WorktreeCreateResult,
    WorktreeDeleteParams,
    WorktreeDeleteResult,
    WorktreeGetByNameParams,
    WorktreeGetByNameResult,
    WorktreeIdentifyParams,
    WorktreeIdentifyResult,
)
from ...shared.protocol import (
    WorktreeInfo as ProtocolWorktreeInfo,
)
from ..registry import register
from ..worktree_ids import make_worktree_id, parse_worktree_id, wtid_to_path
from ..worktree_service import WorktreeService


@register("worktree_list")
def handle_worktree_list(daemon, request: Request, start_time: float) -> Response:
    worktree_infos = daemon.git_manager.list_worktrees()
    worktrees: list[ProtocolWorktreeInfo] = []
    for info in worktree_infos:
        if not info.is_main:
            worktree_name = info.path.name
            worktree_id = make_worktree_id(worktree_name)
            worktrees.append(
                ProtocolWorktreeInfo(
                    wtid=worktree_id,
                    name=worktree_name,
                    absolute_path=str(info.path),
                    branch_name=info.branch,
                    exists=info.exists,
                    is_main=False,
                ),
            )
    from ...shared.protocol import (
        WorktreeListResult,  # import-cycle-safe: protocol is shared schema only
    )

    result = WorktreeListResult(worktrees=worktrees)
    return Response(result=result, id=request.id)



@register("worktree_create", needs_writer=True)
async def handle_worktree_create(
    daemon,
    request: Request,
    start_time: float,
    writer=None,
) -> Response:
    params = WorktreeCreateParams.model_validate(request.params)
    if "/" in params.name:
        raise ValueError(f"Worktree name '{params.name}' cannot contain slashes")
    worktree_path = daemon.config.worktrees_dir / params.name
    branch_name = f"{daemon.config.branch_prefix}{params.name}"
    worktree_id = make_worktree_id(params.name)
    if worktree_path.exists():
        raise ValueError(f"Worktree path {worktree_path} already exists")
    if daemon.config.post_creation_script:
        script = daemon.config.post_creation_script
        if not script.exists() or not script.is_file():
            raise ValueError(
                f"Post-creation script configured but not found or not a file: {script}",
            )
    svc = daemon.worktree_service
    source_path = None
    if params.source_wtid:
        source_path = wtid_to_path(daemon.config, params.source_wtid)
        if not source_path.exists():
            raise ValueError(f"Source worktree path not found: {source_path}")
        src_repo = daemon.git_manager.get_repo(source_path)
        src_branch = src_repo.head.shorthand
    else:
        src_branch = daemon.config.upstream_branch
    svc.create_worktree(
        daemon.config,
        params.name,
        source_worktree=source_path,
        source_branch=src_branch,
    )
    post = None
    if daemon.config.post_creation_script:
        script = daemon.config.post_creation_script
        if not script.exists() or not script.is_file():
            raise FileNotFoundError(
                f"Post-creation script not found at execution time: {script}",
            )
        # run_post_creation_script is async; we stream via the same writer
        post = await WorktreeService.run_post_creation_script(str(script), worktree_path, writer)
    from ...shared.protocol import HookRunResult

    result = WorktreeCreateResult(
        wtid=worktree_id,
        name=params.name,
        absolute_path=str(worktree_path),
        branch_name=branch_name,
        success=True,
        post_hook=(HookRunResult(**post) if post else None),
    )
    return Response(result=result, id=request.id)


@register("worktree_delete")
def handle_worktree_delete(daemon, request: Request, start_time: float) -> Response:
    params = WorktreeDeleteParams.model_validate(request.params)
    worktree_name = parse_worktree_id(params.wtid)
    worktree_path = daemon.config.worktrees_dir / worktree_name
    if not worktree_path.exists():
        raise ValueError(f"Worktree {worktree_name} does not exist at {worktree_path}")
    daemon.git_manager.worktree_remove(str(worktree_path), force=True)
    try:
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
    except Exception as e:
        logging.getLogger(__name__).warning("Filesystem cleanup failed for %s: %s", worktree_path, e)
    result = WorktreeDeleteResult(
        wtid=params.wtid,
        success=True,
        message=f"Deleted worktree {worktree_name}",
    )
    return Response(result=result, id=request.id)


def _resolve_worktree_name_to_info(name: str, worktree_infos: list) -> object | None:
    for info in worktree_infos:
        if (info.is_main and name == MAIN_WORKTREE_DISPLAY_NAME) or (
            not info.is_main and info.path.name == name
        ):
            return info
    return None


@register("worktree_identify")
def handle_worktree_identify(daemon, request: Request, start_time: float) -> Response:
    params = WorktreeIdentifyParams.model_validate(request.params)
    absolute_path = Path(params.absolute_path)
    try:
        rel_path = absolute_path.relative_to(daemon.config.worktrees_dir)
        worktree_name = rel_path.parts[0] if rel_path.parts else None
        if len(rel_path.parts) > 1:
            relative_path = str(Path(*rel_path.parts[1:]))
        else:
            relative_path = ""
    except ValueError:
        try:
            absolute_path.relative_to(daemon.config.main_repo)
            worktree_name = MAIN_WORKTREE_DISPLAY_NAME
            relative_path = str(absolute_path.relative_to(daemon.config.main_repo))
        except ValueError:
            worktree_name = None
            relative_path = None
    if worktree_name and absolute_path.exists():
        worktree_infos = daemon.git_manager.list_worktrees()
        found_worktree = _resolve_worktree_name_to_info(worktree_name, worktree_infos)
        if not found_worktree:
            raise ValueError(f"Path {absolute_path} is not a managed worktree")
        if found_worktree.is_main:
            worktree_id = make_worktree_id(MAIN_WORKTREE_DISPLAY_NAME)
            resolved_name = MAIN_WORKTREE_DISPLAY_NAME
        else:
            worktree_id = make_worktree_id(found_worktree.path.name)
            resolved_name = found_worktree.path.name
        result = WorktreeIdentifyResult(
            wtid=worktree_id,
            name=resolved_name,
            is_worktree=True,
            relative_path=relative_path,
        )
    else:
        raise ValueError(f"Path {absolute_path} is not a managed worktree")
    return Response(result=result, id=request.id)


@register("worktree_get_by_name")
def handle_worktree_get_by_name(daemon, request: Request, start_time: float) -> Response:
    params = WorktreeGetByNameParams.model_validate(request.params)
    name = params.name
    worktree_infos = daemon.git_manager.list_worktrees()
    found_worktree = _resolve_worktree_name_to_info(name, worktree_infos)
    if found_worktree:
        if found_worktree.is_main:
            wtid = make_worktree_id(MAIN_WORKTREE_DISPLAY_NAME)
            worktree_name = MAIN_WORKTREE_DISPLAY_NAME
        else:
            wtid = make_worktree_id(found_worktree.path.name)
            worktree_name = found_worktree.path.name
        result = WorktreeGetByNameResult(
            wtid=wtid,
            name=worktree_name,
            exists=True,
            absolute_path=str(found_worktree.path),
        )
    else:
        result = WorktreeGetByNameResult(
            wtid=None,
            name=None,
            exists=False,
            absolute_path=None,
        )
    return Response(result=result, id=request.id)
