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
    Request,
    Response,
    StatusParams,
    StatusResponse,
    StatusResult,
)
from ..registry import register
from ..types import DiscoveredWorktree
from ..worktree_ids import make_worktree_id, parse_worktree_id


@register("get_status")
async def handle_status_request(daemon, request: Request, start_time: float) -> Response:
    params = StatusParams.model_validate(request.params)
    worktree_ids = params.worktree_ids

    if worktree_ids:
        worktree_paths: list[Path] = []
        for wtid in worktree_ids:
            worktree_name = parse_worktree_id(wtid)
            worktree_path = daemon.config.worktrees_dir / worktree_name
            worktree_paths.append(worktree_path)
    else:
        if not daemon.known_worktrees:
            current = await daemon.discovery_scanner.scan(daemon.config.worktrees_dir)
            changes = daemon.registry.apply(current)
            daemon.known_worktrees = dict(daemon.registry.known)
            for wt in changes.added:
                await daemon._start_gitstatusd_for_worktree(wt)
            for wt in changes.removed:
                await daemon._stop_gitstatusd_for_worktree(wt)
        worktree_paths = list(daemon.known_worktrees.keys())
        git_paths = [wt.path for wt in daemon.git_manager.list_worktrees() if not wt.is_main]
        if git_paths and len(worktree_paths) < len(git_paths):
            for p in git_paths:
                if p not in daemon.known_worktrees and p.exists():
                    wt_info = DiscoveredWorktree(p, p.name)
                    daemon.known_worktrees[p] = wt_info
                    daemon._startup_tasks.append(asyncio.create_task(daemon._start_gitstatusd_for_worktree(wt_info)))
            worktree_paths = list(daemon.known_worktrees.keys())

    results: dict[str, StatusResult] = {}
    individual_times: dict[str, float] = {}

    async def process_single_worktree(worktree_path: Path):
        single_start = time.time()
        gs_client = daemon.gitstatusd_clients.get(worktree_path)
        worktree_last_error: str | None = None
        if gs_client:
            try:
                dirty_files, untracked_files, last_updated_at, have_cache = (
                    gs_client.get_cached_working_status()
                )
                cache_age_ms = (
                    (time.time() - last_updated_at.timestamp()) * 1000 if last_updated_at else None
                )
                if not have_cache:
                    asyncio.create_task(gs_client.update_working_status())
                if last_updated_at is None:
                    last_updated_at = datetime.now()
                    cache_age_ms = None
                try:
                    commit_info_data, ahead_behind, branch_name = (
                        daemon.repo_meta.compute_meta(worktree_path)
                    )
                except Exception as e:  # noqa: F841
                    commit_info_data = None
                    ahead_behind = (0, 0)
                    branch_name = "HEAD"
                    worktree_last_error = "meta error"
                prsvc = daemon.pr_services.get(worktree_path)
                pr_info_data = None
                if prsvc:
                    try:
                        pr_info_data = await asyncio.wait_for(prsvc.get_pr_info(branch_name), timeout=0.75)
                    except asyncio.TimeoutError:
                        pr_info_data = None
                is_cached = have_cache
                is_stale = bool(
                    cache_age_ms and cache_age_ms > daemon.config.cache_refresh_age.total_seconds() * 1000,
                )
                state = GitstatusdState.RUNNING if gs_client.is_running else GitstatusdState.STOPPED
            except asyncio.TimeoutError:
                single_time = (time.time() - single_start) * 1000
                state = GitstatusdState.STARTING
                dirty_files, untracked_files = [], []
                try:
                    commit_info_data, ahead_behind, branch_name = (
                        daemon.repo_meta.compute_meta(worktree_path)
                    )
                except Exception as e:  # noqa: F841
                    commit_info_data = None
                    ahead_behind = (0, 0)
                    branch_name = "HEAD"
                    worktree_last_error = "meta error"
                last_updated_at = datetime.now()
                pr_info_data = None
                is_cached = False
                cache_age_ms = None
                is_stale = False
        else:
            single_time = (time.time() - single_start) * 1000
            state = GitstatusdState.STOPPED
            dirty_files, untracked_files = [], []
            try:
                commit_info_data, ahead_behind, branch_name = (
                    daemon.repo_meta.compute_meta(worktree_path)
                )
            except Exception as e:  # noqa: F841
                commit_info_data = None
                ahead_behind = (0, 0)
                branch_name = "HEAD"
                worktree_last_error = "meta error"
            last_updated_at = datetime.now()
            pr_info_data = None
            is_cached = False
            cache_age_ms = None
            is_stale = False

        commit_info = CommitInfo.model_validate(commit_info_data) if commit_info_data else None
        wtid = make_worktree_id(worktree_path.name)
        pr_info = None
        if pr_info_data:
            pr_info = PRInfo(branch=branch_name, pr_data=coerce_prdata(pr_info_data))
        single_time = (time.time() - single_start) * 1000
        return (
            str(wtid),
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
                is_main=worktree_path.resolve() == daemon.config.main_repo.resolve(),
                upstream_branch=daemon.config.upstream_branch,
                pr_info=pr_info,
                gitstatusd_state=state,
                restarts=0,
                last_error=worktree_last_error,
            ),
            single_time,
        )

    worktree_results = await asyncio.gather(*[process_single_worktree(p) for p in worktree_paths])
    for wtid, status_result, proc_ms in worktree_results:
        results[wtid] = status_result
        individual_times[wtid] = proc_ms

    total_time = (time.time() - start_time) * 1000
    total_wt = len(daemon.known_worktrees)
    with_git = sum(1 for p in daemon.gitstatusd_clients.values() if p.is_running)
    any_wt_error = any(r.last_error for r in results.values())
    github_state = ComponentState.DISABLED
    if daemon.github_interface:
        github_state = ComponentState.OK
        for prsvc in daemon.pr_services.values():
            if prsvc.cached is None:
                github_state = ComponentState.STARTING
                break
    readiness = ReadinessSummary(
        total_worktrees=total_wt,
        with_gitstatusd=with_git,
        discovery_scanning=daemon.discovery_scanning,
        github=github_state,
    )

    components = ComponentsStatus(
        discovery=ComponentStatus(
            state=ComponentState.SCANNING if daemon.discovery_scanning else ComponentState.OK,
        ),
        github=ComponentStatus(state=github_state),
        gitstatusd=ComponentStatus(
            state=ComponentState.OK if (with_git == total_wt and total_wt > 0 and not any_wt_error) else ComponentState.ERROR,
            metrics={"running": with_git, "total": total_wt},
        ),
    )

    status_response = StatusResponse(
        results=dict(results.items()),
        total_processing_time_ms=total_time,
        individual_processing_times_ms=individual_times,
        concurrent_requests=len(worktree_paths),
        daemon_health=daemon.daemon_health,
        readiness_summary=readiness,
        components=components,
    )

    return Response(result=status_response, id=request.id)
