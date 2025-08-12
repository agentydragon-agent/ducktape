from __future__ import annotations

import asyncio
import logging

from .types import DiscoveredWorktree

logger = logging.getLogger(__name__)


class WorktreeDiscovery:
    def __init__(self, daemon):
        self.daemon = daemon
        self._startup_tasks: list[asyncio.Task] = []

    async def discover_once(self) -> None:
        worktrees_dir = self.daemon.config.worktrees_dir_resolved
        if not worktrees_dir.exists():
            return
        self.daemon.discovery_scanning = True
        logger.debug("Scanning for worktrees in %s", worktrees_dir)
        current_worktrees: set[DiscoveredWorktree] = set()
        for path in worktrees_dir.iterdir():
            if path.is_dir():
                if (path / ".git").exists() or (path / ".git").is_file():
                    worktree_info = DiscoveredWorktree(path, path.name)
                    current_worktrees.add(worktree_info)
                if path in self.daemon.known_worktrees:
                    # Update last_seen to current timestamp when seen
                    import time as _t
                    self.daemon.known_worktrees[path].last_seen = _t.time()
                else:
                    logger.info("Discovered new worktree: %s", path.name)
                    self.daemon.known_worktrees[path] = DiscoveredWorktree(path, path.name)
                    # Ensure startup task list exists on discovery instance
                    # (avoid getattr/hasattr per style rules)
                    if self._startup_tasks is None:
                        self._startup_tasks = []
                    self._startup_tasks.append(
                        asyncio.create_task(
                            self.daemon._start_gitstatusd_for_worktree(
                                self.daemon.known_worktrees[path],
                            ),
                        ),
                    )
        disappeared = set(self.daemon.known_worktrees.keys()) - {wt.path for wt in current_worktrees}
        for disappeared_path in disappeared:
            worktree_info = self.daemon.known_worktrees[disappeared_path]
            logger.info("Worktree disappeared: %s", worktree_info.name)
            await self.daemon._stop_gitstatusd_for_worktree(worktree_info)
            del self.daemon.known_worktrees[disappeared_path]
        self.daemon.discovery_scanning = False

    async def periodic_loop(self) -> None:
        while self.daemon.running:
            try:
                await self.discover_once()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in periodic discovery")
                await asyncio.sleep(30)
