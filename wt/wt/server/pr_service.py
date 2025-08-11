from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .github_refresh import DebouncedGitHubRefresh
from .git_manager import GitManager
from .types import DiscoveredWorktree

logger = logging.getLogger(__name__)


class PRService:
    """Manages GitHub PR cache for a single worktree (server-side)."""

    def __init__(self, github_interface, config, worktree_info: DiscoveredWorktree):
        self.github_interface = github_interface
        self.config = config
        self.worktree_info = worktree_info
        self.cached_pr_info: dict[str, Any] | None = None
        self.pr_last_fetched: float | None = None
        self.github_refresh: DebouncedGitHubRefresh | None = None

    async def start(self) -> None:
        if self.github_interface:
            self.github_refresh = DebouncedGitHubRefresh(
                self.worktree_info.path,
                self._refresh_github_cache,
                debounce_delay=self.config.github_debounce_delay.total_seconds(),
                periodic_interval=self.config.github_periodic_interval.total_seconds(),
            )
            await self.github_refresh.start()

    async def stop(self) -> None:
        if self.github_refresh:
            await self.github_refresh.stop()

    async def _refresh_github_cache(self, reason: str, files_changed: list[str]):
        repo = self.worktree_info.path
        try:
            repo_obj = GitManager(config=self.config).get_repo(repo)
            branch_name = repo_obj.head.shorthand
        except Exception:
            return
        await self.get_pr_info(branch_name, force_refresh=True)

    async def get_pr_info(
        self,
        branch_name: str,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        current_time = time.time()
        if (
            not force_refresh
            and self.cached_pr_info is not None
            and self.pr_last_fetched is not None
            and (current_time - self.pr_last_fetched) < 60
        ):
            return self.cached_pr_info
        if not self.github_interface:
            self.cached_pr_info = None
            self.pr_last_fetched = current_time
            return None
        pr_info_data = None
        try:

            def _fetch_pr_info():
                return self.github_interface.pr_search(branch_name)

            loop = asyncio.get_event_loop()
            prs = await loop.run_in_executor(None, _fetch_pr_info)
            if prs:
                pr = prs[0]
                pr_info_data = {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "draft": pr.draft,
                    "mergeable": pr.mergeable,
                    "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "html_url": pr.html_url,
                }
        except Exception:
            pr_info_data = None
        self.cached_pr_info = pr_info_data
        self.pr_last_fetched = current_time
        return pr_info_data
