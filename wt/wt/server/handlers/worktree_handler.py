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
from ..rpc import rpc, Context, Stream, RpcError
from ..worktree_ids import make_worktree_id, parse_worktree_id, wtid_to_path
from ..types import DiscoveredWorktree
from ..worktree_service import WorktreeService

logger = logging.getLogger(__name__)


@rpc.method("worktree_list")
async def worktree_list(ctx: Context) -> WorktreeListResult:
    worktrees: list[WorktreeInfo] = []
    for info in ctx.api.d.git_manager.list_worktrees():
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

    return WorktreeListResult(worktrees=worktrees)


@rpc.stream("worktree_create", params=WorktreeCreateParams)
async def worktree_create(ctx: Context, params: WorktreeCreateParams, stream: Stream[ProgressEvent]) -> WorktreeCreateResult:
    
    if "/" in params.name:
        raise RpcError(code=ErrorCodes.INVALID_PARAMS, message=f"Worktree name '{params.name}' cannot contain slashes")
    worktree_path = ctx.config.worktrees_dir / params.name
    branch_name = f"{ctx.config.branch_prefix}{params.name}"
    worktree_id = make_worktree_id(params.name)
    if worktree_path.exists():
        raise RpcError(code=ErrorCodes.INVALID_PARAMS, message=f"Worktree path {worktree_path} already exists")
    if ctx.config.post_creation_script:
        script = ctx.config.post_creation_script
        if not script.exists() or not script.is_file():
            raise RpcError(code=ErrorCodes.INVALID_PARAMS, message=f"Post-creation script {script} is not a file")
    svc = ctx.api.d.worktree_service
    source_path = None
    if params.source_wtid:
        source_path = wtid_to_path(ctx.config, params.source_wtid)
        if not source_path.exists():
            raise RpcError(code=ErrorCodes.WORKTREE_NOT_FOUND, message=f"Source worktree {source_path} not found")
        src_branch = ctx.api.d.git_manager.get_repo(source_path).head.shorthand
    else:
        src_branch = ctx.config.upstream_branch

    # Emit progress events around the slow hydration/checkout step
    def _emit_progress(step: WorktreeCreateStep, message: str, progress: float):
        stream.emit(ProgressEvent(
            operation=ProgressOperation.WORKTREE_CREATE,
            step=step,
            progress=progress,
            message=message,
        ))

    if source_path:
        _emit_progress(WorktreeCreateStep.HYDRATE_STARTED, "hydrate started", 0.0)
    else:
        _emit_progress(WorktreeCreateStep.CHECKOUT_STARTED, "checkout started", 0.0)

    svc.create_worktree(
        ctx.config,
        params.name,
        source_worktree=source_path,
        source_branch=src_branch,
    )
    # Update daemon registry and index immediately (index-only lookup pathway)
    wt_info = DiscoveredWorktree(worktree_path, worktree_path.name)
    await ctx.api.register_worktree(wt_info)

    if source_path:
        _emit_progress(WorktreeCreateStep.HYDRATE_DONE, "hydrate done", 1.0)
    else:
        _emit_progress(WorktreeCreateStep.CHECKOUT_DONE, "checkout done", 1.0)

    post = None
    if ctx.config.post_creation_script:
        script = ctx.config.post_creation_script
        if not script.exists() or not script.is_file():
            raise RpcError(code=ErrorCodes.INVALID_PARAMS, message=f"Post-creation script not found at execution time: {script}")
        # run_post_creation_script is async; we stream via the same writer
        async def _sink(name: str, data: str) -> None:
            from ...shared.protocol import HookOutputEvent, HookStream
            ev = HookOutputEvent(stream=(HookStream.STDOUT if name == "stdout" else HookStream.STDERR), data=data)
            stream.emit(ev)
        post = await WorktreeService.run_post_creation_script(
            str(script), worktree_path, _sink
        )

    result = WorktreeCreateResult(
        wtid=worktree_id,
        name=params.name,
        absolute_path=str(worktree_path),
        branch_name=branch_name,
        success=True,
        post_hook=(HookRunResult(**post) if post else None),
    )
    return result


@rpc.method("worktree_delete", params=WorktreeDeleteParams)
async def worktree_delete(ctx: Context, params: WorktreeDeleteParams) -> WorktreeDeleteResult:
    worktree_name = parse_worktree_id(params.wtid)
    worktree_path = ctx.config.worktrees_dir / worktree_name
    if not worktree_path.exists():
        raise RpcError(code=ErrorCodes.WORKTREE_NOT_FOUND, message=f"Worktree {worktree_name} does not exist at {worktree_path}")
    ctx.api.d.git_manager.worktree_remove(str(worktree_path), force=True)
    try:
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
    except (OSError, PermissionError) as e:
        logger.warning("Filesystem cleanup failed for %s: %s", worktree_path, e)
    # Update daemon registry and index immediately
    wt_info = DiscoveredWorktree(worktree_path, worktree_name)
    await ctx.api.unregister_worktree(wt_info)
    return WorktreeDeleteResult(
        wtid=params.wtid,
        success=True,
        message=f"Deleted worktree {worktree_name}",
    )


def _resolve_worktree_name_to_info(daemon, name: str) -> object | None:
    if not daemon.worktree_index:
        return None
    if name == MAIN_WORKTREE_DISPLAY_NAME and daemon.worktree_index.main:
        return daemon.worktree_index.main
    return daemon.worktree_index.get_by_name(name)


@rpc.method("worktree_identify", params=WorktreeIdentifyParams)
async def worktree_identify(ctx: Context, params: WorktreeIdentifyParams) -> WorktreeIdentifyResult:
    # params already validated by rpc layer
    absolute_path = Path(params.absolute_path)
    try:
        rel_path = absolute_path.relative_to(ctx.config.worktrees_dir)
        worktree_name = rel_path.parts[0] if rel_path.parts else None
        if len(rel_path.parts) > 1:
            relative_path = str(Path(*rel_path.parts[1:]))
        else:
            relative_path = ""
    except ValueError:
        try:
            absolute_path.relative_to(ctx.config.main_repo)
            worktree_name = MAIN_WORKTREE_DISPLAY_NAME
            relative_path = str(absolute_path.relative_to(ctx.config.main_repo))
        except ValueError:
            worktree_name = None
            relative_path = None
    if not worktree_name or not absolute_path.exists():
        raise RpcError(code=ErrorCodes.WORKTREE_NOT_FOUND, message=f"{absolute_path} is not a managed worktree")
    found_worktree = _resolve_worktree_name_to_info(ctx.api.d, worktree_name)
    if not found_worktree:
        raise RpcError(code=ErrorCodes.WORKTREE_NOT_FOUND, message=f"{absolute_path} is not a managed worktree")
    resolved_name = (
        MAIN_WORKTREE_DISPLAY_NAME
        if found_worktree.path.resolve() == ctx.config.main_repo.resolve()
        else found_worktree.path.name
    )
    return WorktreeIdentifyResult(
        wtid=make_worktree_id(resolved_name),
        name=resolved_name,
        is_worktree=True,
        relative_path=relative_path,
    )


@rpc.method("worktree_get_by_name", params=WorktreeGetByNameParams)
async def worktree_get_by_name(ctx: Context, params: WorktreeGetByNameParams) -> WorktreeGetByNameResult:
    found_worktree = _resolve_worktree_name_to_info(ctx.api.d, params.name)
    if found_worktree:
        worktree_name = (
            MAIN_WORKTREE_DISPLAY_NAME
            if found_worktree.path.resolve() == ctx.config.main_repo.resolve()
            else found_worktree.path.name
        )
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
    return result
