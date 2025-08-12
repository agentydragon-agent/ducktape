"""Unified Git operations manager combining all git functionality."""

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pygit2

from ..shared.git_utils import git_run

if TYPE_CHECKING:
    from ..shared.configuration import Configuration

logger = logging.getLogger(__name__)


# Exception classes for GitManager
class GitError(Exception):
    pass


class GitTimeoutError(GitError):
    pass


class NoSuchRef(GitError):
    pass


class NoSuchBranch(GitError):
    pass


class WorktreeError(GitError):
    pass


class CannotDeleteWorktree(WorktreeError):
    pass


class CannotCreateWorktree(WorktreeError):
    pass


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    exists: bool
    is_main: bool


@dataclass
class GitManager:
    config: "Configuration"

    def __post_init__(self) -> None:
        self._main_repo = pygit2.Repository(str(self.config.main_repo))

    def branch_exists(self, branch_name: str) -> bool:
        return branch_name in self._main_repo.branches

    def create_branch(
        self,
        branch_name: str,
        source_branch: str = "HEAD",
    ) -> None:
        if not self.branch_exists(branch_name):
            target_commit = self._main_repo.revparse_single(source_branch)
            self._main_repo.branches.local.create(branch_name, target_commit)

    async def get_working_directory_status(self) -> tuple[list[str], list[str]]:
        """Get working directory status using fastest available method."""
        try:
            # Get status - dirty (staged/modified) and untracked files
            status = self._main_repo.status()

            dirty_files = []
            untracked_files = []

            for file_path, flags in status.items():
                if (flags & pygit2.GIT_STATUS_WT_MODIFIED) or (
                    flags & pygit2.GIT_STATUS_INDEX_MODIFIED
                ):
                    dirty_files.append(file_path)
                elif flags & pygit2.GIT_STATUS_WT_NEW:
                    untracked_files.append(file_path)

            return dirty_files, untracked_files

        except (pygit2.GitError, OSError) as e:
            # Let callers handle git errors appropriately instead of masking them
            raise GitError(
                f"Failed to get working directory status for {repo_path or self.config.main_repo}: {e}",
            ) from e

    def get_repo(self, path: Path | None = None) -> pygit2.Repository:
        if path is None or path == self.config.main_repo:
            return self._main_repo
        return pygit2.Repository(str(path))

    def get_commit_count_between(
        self,
        rev_a: str,
        rev_b: str,
    ) -> int:
        try:
            ahead, behind = self._main_repo.ahead_behind(rev_b, rev_a)
            return ahead if rev_a == rev_b else (ahead + behind)
        except pygit2.GitError as e:
            raise NoSuchRef(
                f"Cannot count commits between {rev_a} and {rev_b}: {e}",
            ) from e

    def get_commit_info(self, ref: str) -> dict[str, str]:
        try:
            # Resolve reference to commit object
            resolved = self._main_repo.resolve_refish(ref)  # type: ignore[attr-defined]
            commit = resolved[0]
        except KeyError as e:
            raise NoSuchRef(f"Cannot get commit object for {ref}: {e}") from e

        # Extract commit information using pygit2 API
        message = commit.message
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")

        author_name = commit.author.name
        # Convert timestamp to ISO format
        date_obj = datetime.fromtimestamp(commit.commit_time, timezone.utc)
        date_str = date_obj.isoformat()

        return {
            "hash": str(commit.id),
            "short_hash": str(commit.id)[:8],
            "message": message.strip(),
            "author": author_name,
            "date": date_str,
        }

    def verify_ref_exists(self, ref: str) -> str:
        try:
            # Use pygit2 API to resolve the reference
            resolved = self._main_repo.resolve_refish(ref)  # type: ignore[attr-defined]
            return str(resolved[0].id)
        except KeyError as e:
            # Reference does not exist
            raise NoSuchRef(f"Reference does not exist: {ref}") from e
        except Exception as e:
            # Don't assume unknown errors mean "reference doesn't exist"
            raise GitError(f"Failed to verify reference {ref}: {e}") from e

    # Worktree operations
    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all worktrees using pygit2 API."""
        # Main repository is always included
        current_branch = (
            self._main_repo.head.shorthand
            if not self._main_repo.head_is_detached
            else None
        )

        worktree_infos = [
            WorktreeInfo(
                path=self.config.main_repo,
                branch=current_branch or "",
                exists=True,
                is_main=True,
            )
        ]

        # Add all other worktrees
        worktree_infos.extend(
            WorktreeInfo(
                path=Path(self._main_repo.lookup_worktree(wt_name).path),
                branch=wt_name,
                exists=Path(self._main_repo.lookup_worktree(wt_name).path).exists(),
                is_main=False,
            )
            for wt_name in self._main_repo.list_worktrees()
        )

        return worktree_infos

    def worktree_add(self, path: str, branch: str) -> None:
        path_obj = Path(path)

        # Validate path doesn't already exist
        if path_obj.exists():
            raise CannotCreateWorktree(f"Path {path} already exists")

        # Validate branch name format (basic check)
        if not branch or not branch.strip():
            raise CannotCreateWorktree("Branch name cannot be empty")

        # Check if branch name contains valid characters only
        if not re.match(r"^[a-zA-Z0-9._/-]+$", branch):
            raise CannotCreateWorktree(
                f"Branch name '{branch}' contains invalid characters",
            )

        # Check if worktree already exists for this path
        existing_worktrees = self.list_worktrees()
        if any(info.path == path_obj for info in existing_worktrees):
            raise CannotCreateWorktree(f"Worktree already exists at {path}")

        # The branch already exists (created by caller), so we reference it
        branch_ref = self._main_repo.lookup_branch(branch)
        if branch_ref is None:
            raise CannotCreateWorktree(f"Branch {branch} does not exist")

        try:
            git_run(
                ["worktree", "add", "--no-checkout", str(path), branch],
                cwd=self.config.main_repo,
            )
        except subprocess.CalledProcessError as e:
            raise CannotCreateWorktree(
                f"git worktree add failed: {e.stderr.decode(errors='replace').strip()}",
            ) from e

    def worktree_remove(self, path: str, force: bool = False) -> None:
        self._main_repo.lookup_worktree(Path(path).name).prune(force)

    def verify_branch_exists(self, branch_name: str) -> str:
        try:
            return self.verify_ref_exists(f"refs/heads/{branch_name}")
        except NoSuchRef as e:
            raise NoSuchBranch(str(e)) from e
