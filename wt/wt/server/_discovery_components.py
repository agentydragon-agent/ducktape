from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .types import DiscoveredWorktree

logger = logging.getLogger(__name__)


class DiscoveryScanner:
    async def scan(self, worktrees_dir: Path) -> set[DiscoveredWorktree]:
        if not worktrees_dir.exists():
            return set()
        current: set[DiscoveredWorktree] = set()
        for path in worktrees_dir.iterdir():
            if not path.is_dir():
                continue
            if (path / ".git").exists() or (path / ".git").is_file():
                current.add(DiscoveredWorktree(path, path.name))
        return current


@dataclass
class ChangeSet:
    added: list[DiscoveredWorktree] = field(default_factory=list)
    removed: list[DiscoveredWorktree] = field(default_factory=list)
    unchanged: list[DiscoveredWorktree] = field(default_factory=list)


class WorktreeRegistry:
    def __init__(self) -> None:
        self._known: dict[Path, DiscoveredWorktree] = {}

    @property
    def known(self) -> dict[Path, DiscoveredWorktree]:
        return self._known

    def apply(self, current: Iterable[DiscoveredWorktree]) -> ChangeSet:
        cur_map = {wt.path: wt for wt in current}
        added = [cur_map[p] for p in cur_map.keys() - self._known.keys()]
        removed = [self._known[p] for p in self._known.keys() - cur_map.keys()]
        unchanged = [self._known[p] for p in self._known.keys() & cur_map.keys()]
        self._known = cur_map
        return ChangeSet(added=added, removed=removed, unchanged=unchanged)
