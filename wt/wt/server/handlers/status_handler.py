from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from wt.shared.configuration import Configuration

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
from ..rpc import rpc
from ..services import (
    DiscoveryService,
    GitService,
    GitstatusdService,
    HealthService,
    PRServiceProvider,
    StatusService,
    WorktreeIndexService,
)
from ..worktree_ids import make_worktree_id, parse_worktree_id

logger = logging.getLogger(__name__)
_bg_tasks: list[asyncio.Task] = []


@rpc.method("get_status", params=StatusParams)
async def get_status(  # noqa: PLR0913
    status: StatusService,
    gitstat: GitstatusdService,
    prs: PRServiceProvider,
    index: WorktreeIndexService,
    discovery: DiscoveryService,
    health: HealthService,
    git: GitService,
    config: Configuration,
    params: StatusParams,
) -> StatusResponse:
    worktree_ids = params.worktree_ids

    if worktree_ids:
        worktree_paths: list[Path] = []
        for wtid in worktree_ids:
            worktree_name = parse_worktree_id(wtid)
            worktree_path = config.worktrees_dir / worktree_name
            worktree_paths.append(worktree_path)
    else:
        if not index.list_paths():
            logger.debug("Index empty; scheduling discovery run")
            _bg_tasks.append(asyncio.create_task(index.ensure_discovery()))
        worktree_paths = index.list_paths()
        if not worktree_paths:
            # Minimal safe fallback: include main repo to avoid empty UI when daemon just started
            worktree_paths = [config.main_repo]

    items: dict[WorktreeID, StatusItem] = {}

    async def process_single_worktree(worktree_path: Path):
        single_start = time.time()
        gs_client = gitstat.get_client(worktree_path)
        worktree_last_error: str | None = None
        meta = status

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
                    _bg_tasks.append(
                        asyncio.create_task(
                            gs_client.update_working_status(),
                        ),
                    )
                if last_updated_at is None:
                    last_updated_at = datetime.now()
                    cache_age_ms = None
                commit_info_data, ahead_behind, branch_name, worktree_last_error = (
                    _compute_status(worktree_path)
                )
                wt_info = index.get_by_path(worktree_path)
                wtid_cached = (
                    wt_info.wtid if wt_info else make_worktree_id(worktree_path.name)
                )
                pr_info = prs.get_pr_info_cached(wtid_cached, branch_name)
                prs.schedule_pr_refresh(wtid_cached, branch_name)
                is_cached = have_cache
                is_stale = bool(
                    cache_age_ms
                    and cache_age_ms > config.cache_refresh_age.total_seconds() * 1000,
                )
                state = (
                    GitstatusdState.RUNNING
                    if gs_client.is_running
                    else GitstatusdState.STOPPED
                )
            except asyncio.TimeoutError:
                single_time = (time.time() - single_start) * 1000
                state = GitstatusdState.STARTING
                dirty_files, untracked_files = [], []
                commit_info_data, ahead_behind, branch_name, worktree_last_error = (
                    _compute_status(worktree_path)
                )
                last_updated_at = datetime.now()
                pr_info = None
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
            pr_info = None
            is_cached = False
            cache_age_ms = None
            is_stale = False

        commit_info = (
            CommitInfo.model_validate(commit_info_data) if commit_info_data else None
        )
        wtid = make_worktree_id(worktree_path.name)
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
                is_main=worktree_path.resolve() == config.main_repo.resolve(),
                upstream_branch=config.upstream_branch,
                pr_info=pr_info,
                gitstatusd_state=state,
                restarts=0,
                last_error=worktree_last_error,
            ),
            single_time,
        )

    worktree_results = await asyncio.gather(
        *[process_single_worktree(p) for p in worktree_paths],
    )
    total_time = 0.0
    for wtid, status_result, proc_ms in worktree_results:
        items[wtid] = StatusItem(status=status_result, processing_time_ms=proc_ms)
        total_time += proc_ms
    total_wt = len(worktree_paths)
    with_git = sum(
        1
        for p in (gitstat.get_client(pth) for pth in worktree_paths)
        if p and p.is_running
    )
    any_wt_error = any(item.status.last_error for item in items.values())
    github_state = ComponentState.DISABLED
    if config.github_enabled:
        services = prs.values()
        if services:
            github_state = ComponentState.OK
            for prsvc in services:
                if prsvc.cached is None:
                    github_state = ComponentState.STARTING
                    break
        else:
            github_state = ComponentState.ERROR
    readiness = ReadinessSummary(
        total_worktrees=total_wt,
        with_gitstatusd=with_git,
        discovery_scanning=discovery.is_scanning(),
        github=github_state,
    )

    components = ComponentsStatus(
        discovery=ComponentStatus(
            state=(
                ComponentState.SCANNING
                if discovery.is_scanning()
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

    return StatusResponse(
        items=dict(items.items()),
        total_processing_time_ms=total_time,
        concurrent_requests=len(worktree_paths),
        daemon_health=health.health(),
        readiness_summary=readiness,
        components=components,
    )
