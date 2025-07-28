"""Unified Git operations manager combining all git functionality."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pygit2

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
    config: 'Configuration'

    def __post_init__(self) -> None:
        self._repo_cache: dict[Path, pygit2.Repository] = {}
        # Initialize main repository for batch operations
        self._main_repo = pygit2.Repository(str(self.config.main_repo))

    def get_repo(self, path: Path | None = None) -> pygit2.Repository:
        """Get repository instance, defaulting to main repo if path not specified."""
        if path is None:
            return self._main_repo
            
        # Normalize path for consistent caching
        resolved_path = path.resolve()

        if resolved_path in self._repo_cache:
            return self._repo_cache[resolved_path]

        # Create new repo instance
        try:
            repo = pygit2.Repository(str(resolved_path))
            self._repo_cache[resolved_path] = repo
            return repo
        except Exception as e:
            raise GitError(f"Failed to open git repository at {resolved_path}: {e}") from e


    def branch_exists(self, branch_name: str, repo_path: Path | None = None) -> bool:
        repo = self.get_repo(repo_path)
        return branch_name in repo.branches

    def create_branch(self, branch_name: str, source_branch: str = "HEAD", repo_path: Path | None = None) -> None:
        repo = self.get_repo(repo_path)
        if not self.branch_exists(branch_name, repo_path):
            target_commit = repo.revparse_single(source_branch)
            repo.branches.local.create(branch_name, target_commit)

    async def get_working_directory_status(
        self, repo_path: Path | None = None
    ) -> tuple[list[str], list[str]]:
        """Get working directory status using fastest available method."""
        try:
            repo = self.get_repo(repo_path)

            # Get status - dirty (staged/modified) and untracked files
            status = repo.status()

            dirty_files = []
            untracked_files = []

            for file_path, flags in status.items():
                if (
                    flags & pygit2.GIT_STATUS_WT_MODIFIED
                    or flags & pygit2.GIT_STATUS_INDEX_MODIFIED
                ):
                    dirty_files.append(file_path)
                elif flags & pygit2.GIT_STATUS_WT_NEW:
                    untracked_files.append(file_path)

            return dirty_files, untracked_files

        except (pygit2.GitError, OSError) as e:
            # Let callers handle git errors appropriately instead of masking them
            raise GitError(f"Failed to get working directory status for {repo_path or self.config.main_repo}: {e}") from e

    def get_repo_root(self, cwd: Path | None = None) -> Path:
        if cwd is None:
            return self.config.main_repo
        repo = self.get_repo(cwd)
        return Path(repo.workdir).resolve()

    def get_commit_count_between(self, rev_a: str, rev_b: str, repo_path: Path | None = None) -> int:
        repo = self.get_repo(repo_path)
        try:
            ahead, behind = repo.ahead_behind(rev_b, rev_a)
            return ahead if rev_a == rev_b else (ahead + behind)
        except Exception as e:
            raise NoSuchRef(f"Cannot count commits between {rev_a} and {rev_b}: {e}") from e

    def get_commit_info(self, ref: str, repo_path: Path | None = None) -> dict[str, str]:
        repo = self.get_repo(repo_path)
        try:
            # Resolve reference to commit object
            resolved = repo.resolve_refish(ref)
            commit = resolved[0]
        except KeyError as e:
            raise NoSuchRef(f"Cannot get commit object for {ref}: {e}") from e

        # Extract commit information using pygit2 API
        message = commit.message
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")

        author_name = commit.author.name
        # Convert timestamp to ISO format
        from datetime import datetime, timezone

        date_obj = datetime.fromtimestamp(commit.commit_time, timezone.utc)
        date_str = date_obj.isoformat()

        return {
            "hash": str(commit.id),
            "short_hash": str(commit.id)[:8],
            "message": message.strip(),
            "author": author_name,
            "date": date_str,
        }

    def verify_ref_exists(self, ref: str, repo_path: Path | None = None) -> str:
        try:
            repo = self.get_repo(repo_path)
            # Use pygit2 API to resolve the reference
            resolved = repo.resolve_refish(ref)
            return str(resolved[0].id)
        except KeyError as e:
            # Reference does not exist
            raise NoSuchRef(f"Reference does not exist: {ref}") from e
        except Exception as e:
            # Don't assume unknown errors mean "reference doesn't exist"
            raise GitError(f"Failed to verify reference {ref}: {e}") from e

    def get_status_porcelain(self, repo_path: Path | None = None) -> str:
        try:
            repo = self.get_repo(repo_path)
            # Convert pygit2 status to porcelain format
            statuses = repo.status_file_flags()
            lines = []
            for filepath, flags in statuses.items():
                if flags & pygit2.GIT_STATUS_INDEX_NEW:
                    lines.append(f"A  {filepath}")
                elif flags & pygit2.GIT_STATUS_INDEX_MODIFIED:
                    lines.append(f"M  {filepath}")
                elif flags & pygit2.GIT_STATUS_INDEX_DELETED:
                    lines.append(f"D  {filepath}")
                elif flags & pygit2.GIT_STATUS_WT_NEW:
                    lines.append(f"?? {filepath}")
                elif flags & pygit2.GIT_STATUS_WT_MODIFIED:
                    lines.append(f" M {filepath}")
                elif flags & pygit2.GIT_STATUS_WT_DELETED:
                    lines.append(f" D {filepath}")
            return "\n".join(lines)
        except Exception as e:
            raise GitError(f"Git status failed for {repo_path or self.config.main_repo}: {e}") from e

    # Worktree operations
    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all worktrees using pygit2 API."""
        worktree_infos = []
        
        # Main repository is always included
        current_branch = self._main_repo.head.shorthand if not self._main_repo.head_is_detached else None
            
        worktree_infos.append(WorktreeInfo(
            path=self.config.main_repo,
            branch=current_branch,
            exists=True,
            is_main=True
        ))
        
        # Add all other worktrees
        worktree_infos.extend(
            WorktreeInfo(
                path=Path(self._main_repo.lookup_worktree(wt_name).path),
                branch=wt_name,
                exists=Path(self._main_repo.lookup_worktree(wt_name).path).exists(),
                is_main=False
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
            raise CannotCreateWorktree(f"Branch name '{branch}' contains invalid characters")

        # Check if worktree already exists for this path
        existing_worktrees = self.list_worktrees()
        if any(info.path == path_obj for info in existing_worktrees):
            raise CannotCreateWorktree(f"Worktree already exists at {path}")

        # The branch already exists (created by caller), so we reference it
        branch_ref = self._main_repo.lookup_branch(branch)
        if branch_ref is None:
            raise CannotCreateWorktree(f"Branch {branch} does not exist")
        self._main_repo.add_worktree(Path(path).name, path, branch_ref)

    def worktree_remove(self, path: str, force: bool = False) -> None:
        # Get worktree name from path
        worktree_name = Path(path).name
        worktree = self._main_repo.lookup_worktree(worktree_name)
        worktree.prune(force)

    def verify_branch_exists(self, branch_name: str) -> str:
        try:
            return self.verify_ref_exists(f"refs/heads/{branch_name}")
        except NoSuchRef as e:
            raise NoSuchBranch(str(e)) from e

    # Compatibility methods for legacy API
    def status_porcelain(self, cwd: Path | None = None) -> str:
        return self.get_status_porcelain(cwd)

    def rev_count(self, rev_a: str, rev_b: str) -> int:
        return self.get_commit_count_between(rev_a, rev_b)

    def log_format(self, ref: str, format_str: str) -> str:
        try:
            commit_info = self.get_commit_info(ref)
            return f"{commit_info['hash']}|{commit_info['message']}|{commit_info['author']}|{commit_info['date']}"
        except GitError as e:
            raise NoSuchRef(f"Cannot get log for {ref}: {e}") from e

    def repo_root(self, cwd: Path | None = None) -> Path:
        return self.get_repo_root(cwd)