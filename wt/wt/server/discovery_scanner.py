from __future__ import annotations

from pathlib import Path

from .types import DiscoveredWorktree
from .worktree_ids import make_worktree_id


class DiscoveryScanner:
    async def scan(self, worktrees_dir: Path) -> set[DiscoveredWorktree]:
        if not worktrees_dir.exists():
            return set()
        current: set[DiscoveredWorktree] = set()
        for path in worktrees_dir.iterdir():
            if not path.is_dir():
                continue
            if (path / ".git").exists() or (path / ".git").is_file():
                current.add(
                    DiscoveredWorktree(path, path.name, make_worktree_id(path.name)),
                )
        return current
