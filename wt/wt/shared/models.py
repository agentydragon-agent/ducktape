"""Data models and domain objects for worktree management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import click

from .constants import MAIN_WORKTREE_DISPLAY_NAME


@dataclass
class Worktree:
    """Unified worktree representation that eliminates path resolution duplication."""

    name: str
    path: Path
    branch: str
    is_main: bool = False

    @classmethod
    def from_name(cls, name: str, worktrees_dir: Path, branch: str) -> Worktree:
        return cls(name=name, path=worktrees_dir / name, branch=branch)

    @classmethod
    def main_repo(cls, repo_path: Path, branch: str) -> Worktree:
        return cls(name=MAIN_WORKTREE_DISPLAY_NAME, path=repo_path, branch=branch, is_main=True)

    def exists(self) -> bool:
        return self.path.exists()

    def require_exists(self) -> None:
        if not self.exists():
            raise click.ClickException(f"Worktree '{self.name}' does not exist")

    def require_not_exists(self) -> None:
        if self.exists():
            raise click.ClickException(f"Worktree '{self.name}' already exists")

    def resolve_subpath(self, subpath: str) -> Path:
        if subpath.startswith("/"):
            return self.path / subpath[1:]
        if subpath.startswith("./"):
            return self.path / subpath[2:]
        return self.path / subpath


@dataclass
class PRStatus:
    """Unified PR status that eliminates None mergeability confusion."""

    state: Literal["draft", "open", "merged", "closed"]
    mergeable: bool | None = None  # None = unknown/not fetched
    number: int | None = None

    @property
    def display_status(self) -> str:
        if self.state == "merged":
            return "merged"
        if self.state == "closed":
            return "closed"
        if self.state == "draft":
            return "draft"
        if self.mergeable is True:
            return "can merge"
        if self.mergeable is False:
            return "conflict"
        return "open"  # mergeable status unknown


@dataclass
class ProcessInfo:
    """Process information for worktree usage checking."""

    pid: int
    name: str

    def __str__(self) -> str:
        return f"PID {self.pid} ({self.name})"


@dataclass
class SyncStatus:
    """Git sync status (ahead/behind counts)."""

    ahead: int
    behind: int

    @property
    def is_synced(self) -> bool:
        return self.ahead == 0 and self.behind == 0


@dataclass
class WorkingStatus:
    """Working directory status."""

    dirty_files: list[str]
    untracked_files: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.dirty_files and not self.untracked_files

    @property
    def change_count(self) -> int:
        return len(self.dirty_files) + len(self.untracked_files)


@dataclass
class CommitInfo:
    """Commit information with proper datetime handling."""

    last_commit: str
    last_commit_message: str
    last_commit_author: str
    last_commit_date: datetime

    def format_date(self) -> str:
        return self.last_commit_date.strftime("%Y-%m-%d %H:%M")

    @property
    def short_hash(self) -> str:
        return self.last_commit[:8]



@dataclass
class WorktreeParseState:
    """State during git worktree list parsing."""

    path: str | None = None
    branch: str | None = None
    head: str | None = None
    is_bare: bool = False
    is_detached: bool = False

    def finalize(self) -> tuple[Path, str | None] | None:
        if self.path is None:
            return None

        # If detached, clear branch
        final_branch = None if self.is_detached else self.branch
        return (Path(self.path), final_branch)
