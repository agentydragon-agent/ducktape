from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ..shared.github_models import PRData, PRState
from .git_manager import GitManager
from .github_refresh import DebouncedGitHubRefresh
from .types import DiscoveredWorktree

if TYPE_CHECKING:
    from ..shared.configuration import Configuration
    from .github_client import GitHubInterface

logger = logging.getLogger(__name__)


@dataclass
class PRCacheEntry:
    data: PRData | None
    fetched_at: datetime


@dataclass
class PRService:
    """Manages GitHub PR cache for a single worktree (server-side)."""

    github_interface: GitHubInterface | None
    config: Configuration
    worktree_info: DiscoveredWorktree
    git_manager: GitManager
    cached: PRCacheEntry | None = None
    github_refresh: DebouncedGitHubRefresh | None = None

    async def start(self) -> None:
        if self.github_interface:
            self.github_refresh = DebouncedGitHubRefresh(
                self.worktree_info.path,
                self._refresh_github_cache,
                debounce_delay=self.config.github_debounce_delay.total_seconds(),
                periodic_interval=self.config.github_periodic_interval.total_seconds(),
            )
            await self.github_refresh.start()
            # Immediate kick to populate cache on startup (non-blocking)
            self._startup_task = asyncio.create_task(
                self._refresh_github_cache("startup", []),
            )

    async def stop(self) -> None:
        if self.github_refresh:
            await self.github_refresh.stop()

    async def _refresh_github_cache(self, reason: str, files_changed: list[str]):
        repo_obj = self.git_manager.get_repo(self.worktree_info.path)
        branch_name = repo_obj.head.shorthand
        await self.get_pr_info(branch_name, force_refresh=True)

    async def get_pr_info(
        self,
        branch_name: str,
        force_refresh: bool = False,
    ) -> PRData | None:
        now = datetime.now()
        if (
            not force_refresh
            and self.cached is not None
            and (now - self.cached.fetched_at).total_seconds() < 60
        ):
            return self.cached.data
        if not self.github_interface:
            self.cached = PRCacheEntry(data=None, fetched_at=now)
            return None
        pr_info_data: PRData | None = None
        try:
            gh = self.github_interface
            assert gh is not None

            def _fetch_pr_info():
                return gh.pr_search(branch_name)

            loop = asyncio.get_event_loop()
            prs = await loop.run_in_executor(None, _fetch_pr_info)
            if prs:
                pr = prs[0]
                pr_info_data = PRData(
                    pr_number=int(pr.number),
                    pr_state=PRState(pr.state),
                    draft=bool(pr.draft),
                    mergeable=pr.mergeable,
                    merged_at=(pr.merged_at.isoformat() if pr.merged_at else None),
                    additions=pr.additions,
                    deletions=pr.deletions,
                )
        except (OSError, RuntimeError) as e:
            logger.warning("PR fetch failed for %s: %s", branch_name, e)
            pr_info_data = None
        self.cached = PRCacheEntry(data=pr_info_data, fetched_at=now)
        return pr_info_data
