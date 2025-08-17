from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..shared.protocol import WorktreeID

from ..shared.github_models import PRInfo
from ..shared.protocol import DaemonHealth
from .git_manager import GitManager
from .git_manager import WorktreeInfo as GMWorktreeInfo
from .pr_service import PRService
from .repo_status import RepoStatus
from .types import DiscoveredWorktree


class GitService:
    def __init__(self, git_manager: GitManager) -> None:
        self._gm = git_manager

    def list_worktrees(self) -> list[GMWorktreeInfo]:
        return self._gm.list_worktrees()

    def get_repo_head_shorthand(self, path: Path) -> str | None:
        repo = self._gm.get_repo(path)
        return None if repo.head_is_detached else (repo.head.shorthand or "")

    def worktree_remove(self, path: Path, *, force: bool = False) -> None:
        self._gm.worktree_remove(str(path), force=force)


class WorktreeIndexService:
    def __init__(
        self,
        *,
        get_index: Callable[[], object | None],
        rebuild_index: Callable[[], asyncio.Future | asyncio.Task | object],
        run_discovery_once: Callable[[], asyncio.Future | asyncio.Task | object],
    ) -> None:
        self._get_index = get_index
        self._rebuild_index = rebuild_index
        self._run_discovery_once = run_discovery_once

    async def ensure_discovery(self) -> None:
        await asyncio.ensure_future(self._run_discovery_once())  # type: ignore[arg-type]

    async def ensure_index(self) -> None:
        if self._get_index() is None:
            await asyncio.ensure_future(self._rebuild_index())  # type: ignore[arg-type]

    def list_paths(self) -> list[Path]:
        idx = self._get_index()
        if not idx:
            return []
        return list(idx.by_path.keys())  # type: ignore[attr-defined]

    def get_by_path(self, p: Path) -> DiscoveredWorktree | None:
        idx = self._get_index()
        if not idx:
            return None
        return idx.get_by_path(p)  # type: ignore[attr-defined]

    def get_by_name(self, name: str) -> DiscoveredWorktree | None:
        idx = self._get_index()
        if not idx:
            return None
        return idx.get_by_name(name)  # type: ignore[attr-defined]

    def resolve_target(self, name: str | None, current_path: Path):
        idx = self._get_index()
        if not idx:
            return None
        return idx.resolve_target(name, current_path)  # type: ignore[attr-defined]

    def main(self) -> DiscoveredWorktree | None:
        idx = self._get_index()
        if not idx:
            return None
        return idx.main  # type: ignore[attr-defined]


class GitstatusdService:
    def __init__(
        self,
        get_client: Callable[[Path], object | None],
        iter_client_paths: Callable[[], Iterable[Path]] | None = None,
        ensure_watcher_for_path: Callable[
            [Path],
            asyncio.Future | asyncio.Task | object,
        ]
        | None = None,
        list_watchers: Callable[[], list[object]] | None = None,
        clear_watchers: Callable[[], None] | None = None,
    ) -> None:
        self._get_client = get_client
        self._iter_client_paths = iter_client_paths
        self._ensure_watcher_for_path = ensure_watcher_for_path
        self._list_watchers = list_watchers
        self._clear_watchers = clear_watchers

    def get_client(self, path: Path):
        return self._get_client(path)

    def get_cached_status(
        self,
        path: Path,
    ) -> tuple[list[str], list[str], datetime | None, bool]:
        client = self._get_client(path)
        if not client:
            return [], [], None, False
        return client.get_cached_working_status()

    def is_running(self, path: Path) -> bool:
        client = self._get_client(path)
        return bool(client and client.is_running)

    async def start(self) -> None:
        if not (self._iter_client_paths and self._ensure_watcher_for_path):
            return
        for p in list(self._iter_client_paths()):
            if not self._get_client(p):
                continue
            await asyncio.ensure_future(self._ensure_watcher_for_path(p))  # type: ignore[arg-type]

    async def stop(self) -> None:
        if not (self._list_watchers and self._clear_watchers):
            return
        for w in list(self._list_watchers()):
            with contextlib.suppress(Exception):
                await w.stop()
        self._clear_watchers()


class PRServiceProvider:
    def __init__(self, services: dict[WorktreeID, PRService]) -> None:
        self._services = services
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        for svc in self._services.values():
            with contextlib.suppress(Exception):
                await svc.start()

    async def stop(self) -> None:
        for svc in self._services.values():
            with contextlib.suppress(Exception):
                await svc.stop()

    def get_pr_info_cached(self, wtid: WorktreeID, branch: str) -> PRInfo | None:
        prsvc = self._services.get(wtid)
        if not prsvc or not prsvc.cached or not prsvc.cached.data:
            return None
        return PRInfo(branch=branch, pr_data=prsvc.cached.data)

    def schedule_pr_refresh(self, wtid: WorktreeID, branch: str) -> None:
        prsvc = self._services.get(wtid)
        if not prsvc:
            return
        task = asyncio.create_task(prsvc.get_pr_info(branch, force_refresh=True))
        self._tasks.append(task)
        task.add_done_callback(lambda t: self._tasks.remove(t))

    def has(self, wtid: WorktreeID) -> bool:
        return wtid in self._services

    def values(self) -> list[PRService]:
        return list(self._services.values())


class StatusService:
    def __init__(self, repo_status: RepoStatus) -> None:
        self._status = repo_status

    def summarize_status(self, worktree_path: Path):
        return self._status.summarize_status(worktree_path)


class DiscoveryService:
    def __init__(
        self,
        is_scanning: Callable[[], bool],
        periodic: Callable[[], asyncio.Future | asyncio.Task | object] | None = None,
        cancel_periodic: Callable[[], None] | None = None,
    ) -> None:
        self._is_scanning = is_scanning
        self._periodic = periodic
        self._cancel = cancel_periodic

    def is_scanning(self) -> bool:
        return self._is_scanning()

    async def start(self) -> None:
        if self._periodic:
            await asyncio.ensure_future(self._periodic())  # type: ignore[arg-type]

    async def stop(self) -> None:
        if self._cancel:
            self._cancel()


class HealthService:
    def __init__(self, get_health: Callable[[], DaemonHealth]) -> None:
        self._get = get_health

    def health(self) -> DaemonHealth:
        return self._get()


class WorktreeCoordinator:
    def __init__(
        self,
        register_fn: Callable[
            [DiscoveredWorktree],
            asyncio.Future | asyncio.Task | object,
        ],
        unregister_fn: Callable[
            [DiscoveredWorktree],
            asyncio.Future | asyncio.Task | object,
        ],
    ) -> None:
        self._register = register_fn
        self._unregister = unregister_fn

    async def register_worktree(self, wt: DiscoveredWorktree) -> None:
        await asyncio.ensure_future(self._register(wt))  # type: ignore[arg-type]

    async def unregister_worktree(self, wt: DiscoveredWorktree) -> None:
        await asyncio.ensure_future(self._unregister(wt))  # type: ignore[arg-type]
