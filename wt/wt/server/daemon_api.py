from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .git_manager import WorktreeInfo as GMWorktreeInfo
from .types import DiscoveredWorktree
from .worktree_index import WorktreeIndex
from .repo_status import RepoStatus
from ..shared.github_models import PRInfo
from ..shared.protocol import DaemonHealth


@dataclass
class DaemonAPI:
    d: "WtDaemon"

    async def register_worktree(self, wt: DiscoveredWorktree) -> None:
        async with self.d._state_lock:
            self.d.known_worktrees[wt.path] = wt
        await self.d._start_gitstatusd_for_worktree(wt)
        await self.rebuild_index()

    def list_worktrees(self) -> list[GMWorktreeInfo]:
        return self.d.git_manager.list_worktrees()

    def get_gitstatus_client(self, path: Path):
        return self.d.gitstatusd_clients.get(path)

    def list_pr_services(self):
        return list(self.d.pr_services.values())

    def discovery_scanning(self) -> bool:
        return self.d.discovery_scanning

    def daemon_health(self) -> DaemonHealth:
        return self.d.daemon_health

    def get_repo_head_shorthand(self, path: Path) -> str | None:
        repo = self.d.git_manager.get_repo(path)
        return None if repo.head_is_detached else repo.head.shorthand or ""

    def worktree_remove(self, path: Path, *, force: bool = False) -> None:
        self.d.git_manager.worktree_remove(str(path), force=force)

    async def unregister_worktree(self, wt: DiscoveredWorktree) -> None:
        await self.d._stop_gitstatusd_for_worktree(wt)
        async with self.d._state_lock:
            self.d.known_worktrees.pop(wt.path, None)
        await self.rebuild_index()

    async def rebuild_index(self) -> None:
        async with self.d._state_lock:
            self.d.worktree_index = WorktreeIndex.build(
                self.d.known_worktrees.values(), self.d.config.main_repo
            )

    async def get_all_worktree_paths(self) -> list[Path]:
        if not self.d.known_worktrees:
            await self.d._run_discovery_once()
        if not self.d.worktree_index:
            await self.rebuild_index()
        assert self.d.worktree_index is not None
        return list(self.d.worktree_index.by_path.keys())

    def summarize_status(self, worktree_path: Path):
        return self.d.repo_status.summarize_status(worktree_path)

    def get_gitstatus_cached(self, path: Path) -> tuple[list[str], list[str], datetime | None, bool]:
        gs = self.d.gitstatusd_clients.get(path)
        if not gs:
            return [], [], None, False
        return gs.get_cached_working_status()

    def is_gitstatus_running(self, path: Path) -> bool:
        gs = self.d.gitstatusd_clients.get(path)
        return bool(gs and gs.is_running)

    async def get_pr_info(self, worktree_path: Path, branch_name: str, timeout: float = 0.75) -> PRInfo | None:
        prsvc = self.d.pr_services.get(worktree_path)
        if not prsvc:
            return None
        try:
            import asyncio
            data = await asyncio.wait_for(prsvc.get_pr_info(branch_name), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not data:
            return None
        return PRInfo(branch=branch_name, pr_data=data)

    def is_discovery_scanning(self) -> bool:
        return self.d.discovery_scanning

    def total_known_worktrees(self) -> int:
        return len(self.d.known_worktrees)

    def running_gitstatusd_count(self) -> int:
        return sum(1 for p in self.d.gitstatusd_clients.values() if p.is_running)

    def get_daemon_health(self) -> DaemonHealth:
        return self.d.daemon_health

    def get_worktree_by_name(self, name: str) -> DiscoveredWorktree | None:
        idx = self.d.worktree_index
        if not idx:
            return None
        return idx.get_by_name(name)

    def resolve_target(self, name: str | None, current_path: Path):
        idx = self.d.worktree_index
        if not idx:
            return None
        return idx.resolve_target(name, current_path)

    def list_known_worktrees(self) -> list[DiscoveredWorktree]:
        return list(self.d.known_worktrees.values())
