from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from ...shared.github_models import PRInfo, coerce_prdata
from ...shared.protocol import (
    CommitInfo,
    ComponentsStatus,
    ComponentState,
    ComponentStatus,
    GitstatusdState,
    ReadinessSummary,
    StatusItem,
    StatusParams,
    StatusResponse,
    StatusResult,
    WorktreeID,
)
from ..rpc import rpc, Context, RpcError
from ..worktree_index import WorktreeIndex

from ..types import DiscoveredWorktree
from ..worktree_ids import make_worktree_id, parse_worktree_id


@rpc.method("get_status", params=StatusParams)
async def get_status(ctx: Context, params: StatusParams) -> StatusResponse:
    worktree_ids = params.worktree_ids

    if worktree_ids:
        worktree_paths: list[Path] = []
        for wtid in worktree_ids:
            worktree_name = parse_worktree_id(wtid)
            worktree_path = ctx.config.worktrees_dir / worktree_name
            worktree_paths.append(worktree_path)
    else:
        if not ctx.api.d.known_worktrees:
            await ctx.api.d._run_discovery_once()
        if not ctx.api.d.worktree_index:
            await ctx.api.rebuild_index()
        worktree_paths = list(ctx.api.d.worktree_index.by_path.keys())

    items: dict[WorktreeID, StatusItem] = {}

    async def process_single_worktree(worktree_path: Path):
        single_start = time.time()
        gs_client = ctx.api.d.gitstatusd_clients.get(worktree_path)
        worktree_last_error: str | None = None
        meta = ctx.api.d.repo_status

        def _compute_status(path: Path):
            return (*meta.summarize_status(path), None)

        if gs_client:
            try:
                dirty_files, untracked_files, last_updated_at, have_cache = (
                    gs_client.get_cached_working_status()
                )
                cache_age_ms = (
                    (time.time() - last_updated_at.timestamp()) * 1000
                    if last_updated_at
                    else None
                )
                if not have_cache:
                    _update_task = asyncio.create_task(
                        gs_client.update_working_status()
                    )
                if last_updated_at is None:
                    last_updated_at = datetime.now()
                    cache_age_ms = None
                commit_info_data, ahead_behind, branch_name, worktree_last_error = (
                    _compute_status(worktree_path)
                )
                prsvc = ctx.api.d.pr_services.get(worktree_path)
                pr_info_data = None
                if prsvc:
                    try:
                        pr_info_data = await asyncio.wait_for(
                            prsvc.get_pr_info(branch_name), timeout=0.75
                        )
                    except asyncio.TimeoutError:
                        pr_info_data = None
                is_cached = have_cache
                is_stale = bool(
                    cache_age_ms
                    and cache_age_ms
                    > ctx.config.cache_refresh_age.total_seconds() * 1000,
                )
                state = (
                    GitstatusdState.RUNNING if gs_client.is_running else GitstatusdState.STOPPED
                )
            except asyncio.TimeoutError:
                single_time = (time.time() - single_start) * 1000
                state = GitstatusdState.STARTING
                dirty_files, untracked_files = [], []
                commit_info_data, ahead_behind, branch_name, worktree_last_error = (
                    _compute_status(worktree_path)
                )
                last_updated_at = datetime.now()
                pr_info_data = None
                is_cached = False
                cache_age_ms = None
                is_stale = False
        else:
            single_time = (time.time() - single_start) * 1000
            state = GitstatusdState.STOPPED
            dirty_files, untracked_files = [], []
            commit_info_data, ahead_behind, branch_name, worktree_last_error = (
                _compute_status(worktree_path)
            )
            last_updated_at = datetime.now()
            pr_info_data = None
            is_cached = False
            cache_age_ms = None
            is_stale = False

        commit_info = (
            CommitInfo.model_validate(commit_info_data) if commit_info_data else None
        )
        wtid = make_worktree_id(worktree_path.name)
        pr_info = None
        if pr_info_data:
            pr_info = PRInfo(branch=branch_name, pr_data=coerce_prdata(pr_info_data))
        single_time = (time.time() - single_start) * 1000
        return (
            wtid,
            StatusResult(
                wtid=wtid,
                name=worktree_path.name,
                absolute_path=str(worktree_path),
                branch_name=branch_name,
                has_dirty_files=len(dirty_files) > 0,
                has_untracked_files=len(untracked_files) > 0,
                processing_time_ms=single_time,
                last_updated_at=last_updated_at,
                is_cached=is_cached,
                cache_age_ms=cache_age_ms,
                is_stale=is_stale,
                commit_info=commit_info,
                ahead_count=ahead_behind[0],
                behind_count=ahead_behind[1],
                is_main=worktree_path.resolve() == ctx.config.main_repo.resolve(),
                upstream_branch=ctx.config.upstream_branch,
                pr_info=pr_info,
                gitstatusd_state=state,
                restarts=0,
                last_error=worktree_last_error,
            ),
            single_time,
        )

    worktree_results = await asyncio.gather(
        *[process_single_worktree(p) for p in worktree_paths]
    )
    for wtid, status_result, proc_ms in worktree_results:
        items[wtid] = StatusItem(status=status_result, processing_time_ms=proc_ms)

    total_time = (time.time() - ctx.start_time) * 1000
    total_wt = len(ctx.api.d.known_worktrees)
    with_git = sum(1 for p in ctx.api.d.gitstatusd_clients.values() if p.is_running)
    any_wt_error = any(item.status.last_error for item in items.values())
    github_state = ComponentState.DISABLED
    if ctx.api.d.github_interface:
        github_state = ComponentState.OK
        for prsvc in ctx.api.d.pr_services.values():
            if prsvc.cached is None:
                github_state = ComponentState.STARTING
                break
    readiness = ReadinessSummary(
        total_worktrees=total_wt,
        with_gitstatusd=with_git,
        discovery_scanning=ctx.daemon.discovery_scanning,
        github=github_state,
    )

    components = ComponentsStatus(
        discovery=ComponentStatus(
            state=(
                ComponentState.SCANNING
                if ctx.api.d.discovery_scanning
                else ComponentState.OK
            ),
        ),
        github=ComponentStatus(state=github_state),
        gitstatusd=ComponentStatus(
            state=(
                ComponentState.OK
                if (with_git == total_wt and total_wt > 0 and not any_wt_error)
                else ComponentState.ERROR
            ),
            metrics={"running": with_git, "total": total_wt},
        ),
    )

    status_response = StatusResponse(
        items=dict(items.items()),
        total_processing_time_ms=total_time,
        concurrent_requests=len(worktree_paths),
        daemon_health=ctx.api.d.daemon_health,
        readiness_summary=readiness,
        components=components,
    )

    return status_response
