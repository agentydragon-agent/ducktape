"""Git interface with custom exception handling."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .github_models import PRInfo
from .models import CommitInfo


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
    repo_path: Path
    github_repo: str

    def __post_init__(self) -> None:
        # Initialize GitPython Repo object for batch operations
        # Initialize libgit2 repository for batch operations
        import pygit2

        self._repo = pygit2.Repository(str(self.repo_path))

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
        check: bool = True,
        text: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git"] + args,
                cwd=cwd or self.repo_path,
                timeout=timeout,
                check=check,
                text=text,
                capture_output=capture_output,
            )
        except subprocess.TimeoutExpired as e:
            raise GitTimeoutError(f"Git command timed out: {' '.join(args)}") from e
        except subprocess.CalledProcessError as e:
            raise GitError(f"Git command failed: {' '.join(args)}: {e}") from e

    def _run_gh(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        text: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["gh"] + args,
                timeout=timeout,
                check=True,
                text=text,
                capture_output=capture_output,
            )
        except subprocess.TimeoutExpired as e:
            raise GitTimeoutError(f"GitHub CLI command timed out: {' '.join(args)}") from e
        except subprocess.CalledProcessError as e:
            from .github_models import GitHubError

            raise GitHubError(f"GitHub CLI command failed: {' '.join(args)}: {e}") from e

    def worktree_list(self) -> str:
        return self._run_git(["worktree", "list", "--porcelain"]).stdout

    def parse_worktree_list(self, output: str) -> list[tuple[Path, str | None]]:
        from .models import WorktreeParseState

        if not output.strip():
            return []

        worktrees: list[tuple[Path, str | None]] = []
        current_worktree = WorktreeParseState()

        for line in output.strip().split("\n"):
            if not line.strip():
                continue

            if line.startswith("worktree "):
                # Finalize previous worktree if exists
                if result := current_worktree.finalize():
                    worktrees.append(result)

                # Start new worktree
                current_worktree = WorktreeParseState(path=line.removeprefix("worktree ").strip())

            elif line.startswith("branch "):
                branch_ref = line.removeprefix("branch ").strip()
                # Remove refs/heads/ prefix if present
                if branch_ref.startswith("refs/heads/"):
                    branch_ref = branch_ref.removeprefix("refs/heads/")
                current_worktree.branch = branch_ref if branch_ref else None

            elif line.startswith("HEAD "):
                # Store HEAD info but don't use it for branch name
                current_worktree.head = line.removeprefix("HEAD ").strip()

            elif line.startswith("bare"):
                current_worktree.is_bare = True

            elif line.startswith("detached"):
                current_worktree.is_detached = True

        # Add the last worktree
        if result := current_worktree.finalize():
            worktrees.append(result)

        return worktrees

    def status_porcelain(self, cwd: Path | None = None) -> str:
        # Use GitPython instead of raw git commands
        from ..server.git_manager import git_repo_manager

        try:
            repo_path = cwd or self.repo_path
            return git_repo_manager.get_status_porcelain(repo_path)
        except RuntimeError as e:
            raise GitError(str(e)) from e

    def rev_count(self, rev_a: str, rev_b: str) -> int:
        # Use GitPython instead of raw git commands
        from ..server.git_manager import git_repo_manager

        try:
            return git_repo_manager.get_commit_count_between(self.repo_path, rev_a, rev_b)
        except RuntimeError as e:
            raise NoSuchRef(f"Cannot count commits between {rev_a} and {rev_b}: {e}") from e

    def log_format(self, ref: str, format_str: str) -> str:
        # Use GitPython instead of raw git commands
        from ..server.git_manager import git_repo_manager

        try:
            commit_info = git_repo_manager.get_commit_info(self.repo_path, ref)
            return f"{commit_info['hash']}|{commit_info['message']}|{commit_info['author']}|{commit_info['date']}"
        except RuntimeError as e:
            raise NoSuchRef(f"Cannot get log for {ref}: {e}") from e
        except GitError as e:
            raise NoSuchRef(f"Cannot get log for {ref}: {e}") from e

    def batch_commit_info(self, branches: list[str]) -> dict[str, dict[str, str]]:
        """
        Batch retrieve commit info for multiple branches via pygit2.
        Returns mapping: branch -> dict with keys hash, message, author, date, short_hash.
        """
        result: dict[str, dict[str, str]] = {}
        for branch in branches:
            ref_name = f"refs/heads/{branch}"
            try:
                ref = self._repo.references[ref_name]
                commit = self._repo.get(ref.target)
            except KeyError:
                continue
            # Format commit date with timezone offset
            from datetime import datetime, timedelta, timezone

            tz = timezone(timedelta(minutes=commit.commit_time_offset))
            date = datetime.fromtimestamp(commit.commit_time, tz=tz).isoformat()
            oid_str = str(commit.id)
            result[branch] = {
                "hash": oid_str,
                "short_hash": oid_str[:8],
                "message": commit.message.splitlines()[0],
                "author": commit.author.name,
                "date": date,
            }
        return result

    def batch_ahead_behind(
        self, default_branch: str, branches: list[str]
    ) -> dict[str, tuple[int, int]]:
        """
        Batch retrieve ahead/behind counts of branches relative to default_branch via pygit2 graph API.
        Returns mapping: branch -> (ahead, behind).
        """
        result: dict[str, tuple[int, int]] = {}
        try:
            default_ref = self._repo.references[f"refs/heads/{default_branch}"]
            default_oid = default_ref.target
        except KeyError:
            return result
        for branch in branches:
            try:
                ref = self._repo.references[f"refs/heads/{branch}"]
                ahead, behind = self._repo.ahead_behind(default_oid, ref.target)
                result[branch] = (ahead, behind)
            except KeyError:
                continue
        return result

    def reflog_recent(self, since: str = "10 minutes ago") -> str:
        return self._run_git(["reflog", f"--since={since}"], check=False).stdout

    def repo_root(self, cwd: Path | None = None) -> Path:
        # Use GitPython instead of raw git commands
        from ..server.git_manager import git_repo_manager

        try:
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
        existing_worktrees = self.parse_worktree_list(self.worktree_list())
        if any(wt_path == path_obj for wt_path, _ in existing_worktrees):
            raise CannotCreateWorktree(f"Worktree already exists at {path}")

        try:
            self._run_git(["worktree", "add", path, branch])
        except GitError as e:
            raise CannotCreateWorktree(f"Cannot create worktree at {path}: {e}") from e

    def worktree_remove(self, path: str, force: bool = False) -> None:
        try:
            args = ["worktree", "remove", path]
            if force:
                args.append("--force")
            self._run_git(args)
        except GitError as e:
            raise CannotDeleteWorktree(f"Cannot delete worktree at {path}: {e}") from e

    def show_ref_verify(self, ref: str) -> str:
        try:
            result = self._run_git(["show-ref", "--verify", ref])
            return result.stdout.strip()
        except GitError as e:
            raise NoSuchRef(f"Reference does not exist: {ref}") from e

    def verify_branch_exists(self, branch_name: str) -> str:
        # Use GitRepositoryManager instead of raw git commands
        from ..server.git_manager import GitRepositoryManager

        try:
            manager = GitRepositoryManager()
            return manager.verify_ref_exists(self.repo_path, f"refs/heads/{branch_name}")
        except RuntimeError as e:
            raise NoSuchRef(str(e)) from e

    def branch_create(self, branch_name: str, start_point: str = "HEAD") -> None:
        try:
            self._run_git(["branch", branch_name, start_point])
        except GitError as e:
            raise NoSuchBranch(f"Cannot create branch {branch_name}: {e}") from e

    def get_remote_ref_commit_time(self, branch_name: str) -> float:
        ref_name = f"refs/remotes/origin/{branch_name}"
        result = self._run_git(["log", "-1", "--format=%ct", ref_name])
        return float(result.stdout.strip())
