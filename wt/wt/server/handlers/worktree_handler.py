from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ...shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from ...shared.protocol import (
    HookRunResult,
    ProgressEvent,
    ProgressOperation,
    Request,
    Response,
    WorktreeCreateParams,
    WorktreeCreateResult,
    WorktreeCreateStep,
    WorktreeDeleteParams,
    WorktreeDeleteResult,
    WorktreeGetByNameParams,
    WorktreeGetByNameResult,
    WorktreeIdentifyParams,
    WorktreeIdentifyResult,
    WorktreeInfo,
    WorktreeListResult,
)
from ..registry import register
from ..worktree_ids import make_worktree_id, parse_worktree_id, wtid_to_path
from ..worktree_service import WorktreeService

logger = logging.getLogger(__name__)


@register("worktree_list")
def handle_worktree_list(daemon, request: Request, start_time: float) -> Response:
    worktrees: list[WorktreeInfo] = []
    for info in daemon.git_manager.list_worktrees():
        if not info.is_main:
            worktree_name = info.path.name
            worktree_id = make_worktree_id(worktree_name)
            worktrees.append(
                WorktreeInfo(
                    wtid=worktree_id,
                    name=worktree_name,
                    absolute_path=str(info.path),
                    branch_name=info.branch,
                    exists=info.exists,
                    is_main=False,
                ),
            )

    return Response(result=WorktreeListResult(worktrees=worktrees), id=request.id)


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
            raise ValueError(f"Post-creation script {script} is not a file")
    svc = daemon.worktree_service
    source_path = None
    if params.source_wtid:
        source_path = wtid_to_path(daemon.config, params.source_wtid)
        if not source_path.exists():
            raise ValueError(f"Source worktree {source_path} not found")
        src_branch = daemon.git_manager.get_repo(source_path).head.shorthand
    else:
        src_branch = daemon.config.upstream_branch

    # Emit progress events around the slow hydration/checkout step
    def _emit_progress(step: WorktreeCreateStep, message: str, progress: float):
        if writer is None:
            return
        evt = ProgressEvent(
            operation=ProgressOperation.WORKTREE_CREATE,
            step=step,
            progress=progress,
            message=message,
        )
        writer.write((evt.model_dump_json() + "\n").encode())

    if source_path:
        _emit_progress(WorktreeCreateStep.HYDRATE_STARTED, "hydrate started", 0.0)
    else:
        _emit_progress(WorktreeCreateStep.CHECKOUT_STARTED, "checkout started", 0.0)

    svc.create_worktree(
        daemon.config,
        params.name,
        source_worktree=source_path,
        source_branch=src_branch,
    )

    if source_path:
        _emit_progress(WorktreeCreateStep.HYDRATE_DONE, "hydrate done", 1.0)
    else:
        _emit_progress(WorktreeCreateStep.CHECKOUT_DONE, "checkout done", 1.0)

    post = None
    if daemon.config.post_creation_script:
        script = daemon.config.post_creation_script
        if not script.exists() or not script.is_file():
            raise FileNotFoundError(
                f"Post-creation script not found at execution time: {script}",
            )
        # run_post_creation_script is async; we stream via the same writer
        post = await WorktreeService.run_post_creation_script(
            str(script), worktree_path, writer
        )

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
    except (OSError, PermissionError) as e:
        logger.warning("Filesystem cleanup failed for %s: %s", worktree_path, e)
    return Response(
        result=WorktreeDeleteResult(
            wtid=params.wtid,
            success=True,
            message=f"Deleted worktree {worktree_name}",
        ),
        id=request.id,
    )


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
    if not worktree_name or not absolute_path.exists():
        raise ValueError(f"{absolute_path} is not a managed worktree")
    worktree_infos = daemon.git_manager.list_worktrees()
    found_worktree = _resolve_worktree_name_to_info(worktree_name, worktree_infos)
    if not found_worktree:
        raise ValueError(f"{absolute_path} is not a managed worktree")
    if found_worktree.is_main:
        resolved_name = MAIN_WORKTREE_DISPLAY_NAME
    else:
        resolved_name = found_worktree.path.name
    return Response(
        result=WorktreeIdentifyResult(
            wtid=make_worktree_id(resolved_name),
            name=resolved_name,
            is_worktree=True,
            relative_path=relative_path,
        ),
        id=request.id,
    )


@register("worktree_get_by_name")
def handle_worktree_get_by_name(
    daemon, request: Request, start_time: float
) -> Response:
    params = WorktreeGetByNameParams.model_validate(request.params)
    worktree_infos = daemon.git_manager.list_worktrees()
    found_worktree = _resolve_worktree_name_to_info(params.name, worktree_infos)
    if found_worktree:
        if found_worktree.is_main:
            worktree_name = MAIN_WORKTREE_DISPLAY_NAME
        else:
            worktree_name = found_worktree.path.name
        result = WorktreeGetByNameResult(
            wtid=make_worktree_id(worktree_name),
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
