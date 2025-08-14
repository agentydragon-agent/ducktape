from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..shared.configuration import Configuration
from ..shared.github_models import PRInfo
from ..shared.protocol import DaemonHealth
from .git_manager import GitManager, WorktreeInfo as GMWorktreeInfo
from .repo_status import RepoStatus
from .types import DiscoveredWorktree
from .pr_service import PRService


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
    def __init__(self, get_client: Callable[[Path], object | None]) -> None:
        self._get_client = get_client

    def get_client(self, path: Path):
        return self._get_client(path)

    def get_cached_status(self, path: Path) -> tuple[list[str], list[str], datetime | None, bool]:
        client = self._get_client(path)
        if not client:
            return [], [], None, False
        return client.get_cached_working_status()

    def is_running(self, path: Path) -> bool:
        client = self._get_client(path)
        return bool(client and client.is_running)


class PRServiceProvider:
    def __init__(
        self,
        get_service: Callable[[Path], PRService | None],
        list_services: Callable[[], list[PRService]],
    ) -> None:
        self._get = get_service
        self._list = list_services

    async def get_pr_info(self, path: Path, branch: str, timeout: float = 0.75) -> PRInfo | None:
        prsvc = self._get(path)
        if not prsvc:
            return None
        try:
            data = await asyncio.wait_for(prsvc.get_pr_info(branch), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not data:
            return None
        return PRInfo(branch=branch, pr_data=data)

    def list_services(self) -> list[PRService]:
        return list(self._list())


class StatusService:
    def __init__(self, repo_status: RepoStatus) -> None:
        self._status = repo_status

    def summarize_status(self, worktree_path: Path):
        return self._status.summarize_status(worktree_path)


class DiscoveryService:
    def __init__(self, is_scanning: Callable[[], bool]) -> None:
        self._is_scanning = is_scanning

    def is_scanning(self) -> bool:
        return self._is_scanning()


class HealthService:
    def __init__(self, get_health: Callable[[], DaemonHealth]) -> None:
        self._get = get_health

    def health(self) -> DaemonHealth:
        return self._get()


class WorktreeCoordinator:
    def __init__(
        self,
        register_fn: Callable[[DiscoveredWorktree], asyncio.Future | asyncio.Task | object],
        unregister_fn: Callable[[DiscoveredWorktree], asyncio.Future | asyncio.Task | object],
    ) -> None:
        self._register = register_fn
        self._unregister = unregister_fn

    async def register_worktree(self, wt: DiscoveredWorktree) -> None:
        await asyncio.ensure_future(self._register(wt))  # type: ignore[arg-type]

    async def unregister_worktree(self, wt: DiscoveredWorktree) -> None:
        await asyncio.ensure_future(self._unregister(wt))  # type: ignore[arg-type]
