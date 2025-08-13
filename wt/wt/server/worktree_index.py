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

    def resolve_target(self, name: str | None, current_path: Path) -> tuple[DiscoveredWorktree, str | None] | None:
        if name:
            if name == ".":
                # Current worktree by path
                for wt in self.by_path.values():
                    if current_path.is_relative_to(wt.path):
                        rel = str(current_path.relative_to(wt.path))
                        return wt, rel
                return None
            if name in self.by_name:
                return self.by_name[name], None
            if self.main and name == "main":
                return self.main, None
            return None
        # No name provided: infer from current path
        if current_path.is_relative_to(self.main.path) if self.main else False:
            rel = str(current_path.relative_to(self.main.path))
            return self.main, rel
        for wt in self.by_path.values():
            if current_path.is_relative_to(wt.path):
                rel = str(current_path.relative_to(wt.path))
                return wt, rel
        return None
