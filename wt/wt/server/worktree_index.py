from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .types import DiscoveredWorktree


@dataclass
class WorktreeIndex:
    by_path: dict[Path, DiscoveredWorktree]
    by_name: dict[str, DiscoveredWorktree]
    main: DiscoveredWorktree | None

    @classmethod
    def build(cls, worktrees: Iterable[DiscoveredWorktree], main_repo: Path) -> "WorktreeIndex":
        by_path: dict[Path, DiscoveredWorktree] = {}
        by_name: dict[str, DiscoveredWorktree] = {}
        main: DiscoveredWorktree | None = None
        for wt in worktrees:
            by_path[wt.path] = wt
            by_name[wt.name] = wt
            if wt.path.resolve() == main_repo.resolve():
                main = wt
        return cls(by_path=by_path, by_name=by_name, main=main)

    def get_by_path(self, p: Path) -> DiscoveredWorktree | None:
        return self.by_path.get(p)

    def get_by_name(self, name: str) -> DiscoveredWorktree | None:
        return self.by_name.get(name)
