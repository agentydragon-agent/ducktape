from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .pr_service import PRService
from .worktree_registry import ChangeSet


@dataclass
class WorktreeOrchestrator:
    daemon: any  # WtDaemon

    async def apply(self, changes: ChangeSet) -> None:
        # Stop removed
        for wt in changes.removed:
            await self.daemon._stop_gitstatusd_for_worktree(wt)
        # Start added
        for wt in changes.added:
            await self.daemon._start_gitstatusd_for_worktree(wt)
