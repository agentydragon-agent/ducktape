"""Git interface with custom exception handling."""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .github_models import PRInfo
from .models import CommitInfo

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .configuration import Configuration


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
    """Cannot create worktree."""

    pass


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    exists: bool
    is_main: bool


@dataclass
class WorktreeStatus:
    name: str
    branch: str
    ahead: int
    behind: int
    dirty_files: list[str]
    untracked_files: list[str]
    default_branch: str
    commit_info: CommitInfo | None
    error: str | None = None
    pr_info: PRInfo | None = None  # GitHub PR information from daemon


# PullRequestCache moved to github_models.py
# Import it if needed


@dataclass
class GitInterface:
    config: 'Configuration'  # Forward reference for type hint

    def __post_init__(self) -> None:
        # Initialize libgit2 repository for batch operations
        import pygit2

        self._repo = pygit2.Repository(str(self.config.main_repo))



    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all worktrees using pygit2 API."""
        worktree_infos = []
        
        # Main repository is always included
        current_branch = self._repo.head.shorthand if not self._repo.head_is_detached else None
            
        worktree_infos.append(WorktreeInfo(
            path=self.config.main_repo,
            branch=current_branch,
            exists=True,
            is_main=True
        ))
        
        # Add all other worktrees
        worktree_infos.extend(
            WorktreeInfo(
                path=Path(self._repo.lookup_worktree(wt_name).path),
                branch=wt_name,
                exists=Path(self._repo.lookup_worktree(wt_name).path).exists(),
                is_main=False
            )
            for wt_name in self._repo.list_worktrees()
        )
                
        return worktree_infos


    def status_porcelain(self, cwd: Path | None = None) -> str:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            git_repo_manager = GitRepositoryManager()
            repo_path = cwd or self.config.main_repo
            return git_repo_manager.get_status_porcelain(repo_path)
        except RuntimeError as e:
            raise GitError(str(e)) from e

    def rev_count(self, rev_a: str, rev_b: str) -> int:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            git_repo_manager = GitRepositoryManager()
            return git_repo_manager.get_commit_count_between(self.config.main_repo, rev_a, rev_b)
        except RuntimeError as e:
            raise NoSuchRef(f"Cannot count commits between {rev_a} and {rev_b}: {e}") from e

    def log_format(self, ref: str, format_str: str) -> str:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            git_repo_manager = GitRepositoryManager()
            commit_info = git_repo_manager.get_commit_info(self.config.main_repo, ref)
            return f"{commit_info['hash']}|{commit_info['message']}|{commit_info['author']}|{commit_info['date']}"
        except RuntimeError as e:
            raise NoSuchRef(f"Cannot get log for {ref}: {e}") from e
        except GitError as e:
            raise NoSuchRef(f"Cannot get log for {ref}: {e}") from e




    def repo_root(self, cwd: Path | None = None) -> Path:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            git_repo_manager = GitRepositoryManager()
            return git_repo_manager.get_repo_root(cwd)
        except RuntimeError as e:
            raise GitError(str(e)) from e

    # Note: GitHub operations should be handled separately, not mixed with git operations

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
            raise CannotCreateWorktree(f"Branch name '{branch}' contains invalid characters")

        # Check if worktree already exists for this path
        existing_worktrees = self.list_worktrees()
        if any(info.path == path_obj for info in existing_worktrees):
            raise CannotCreateWorktree(f"Worktree already exists at {path}")

        # The branch already exists (created by WorktreeService), so we reference it
        branch_ref = self._repo.lookup_branch(branch)
        if branch_ref is None:
            raise CannotCreateWorktree(f"Branch {branch} does not exist")
        self._repo.add_worktree(Path(path).name, path, branch_ref)

    def worktree_remove(self, path: str, force: bool = False) -> None:
        # Get worktree name from path
        worktree_name = Path(path).name
        worktree = self._repo.lookup_worktree(worktree_name)
        worktree.prune(force)


    def verify_branch_exists(self, branch_name: str) -> str:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            manager = GitRepositoryManager()
            return manager.verify_ref_exists(self.config.main_repo, f"refs/heads/{branch_name}")
        except RuntimeError as e:
            raise NoSuchRef(str(e)) from e

    def branch_create(self, branch_name: str, start_point: str = "HEAD") -> None:
        target_commit = self._repo.revparse_single(start_point)
        self._repo.branches.local.create(branch_name, target_commit)

