"""Centralized GitPython repository management."""

import logging
from pathlib import Path

import pygit2

logger = logging.getLogger(__name__)


class GitRepositoryManager:
    def __init__(self):
        self._repo_cache: dict[Path, pygit2.Repository] = {}

    def get_repo(self, path: Path) -> pygit2.Repository:
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
            raise RuntimeError(f"Failed to open git repository at {resolved_path}: {e}") from e


    def get_default_branch(self, repo_path: Path) -> str:
        repo = self.get_repo(repo_path)
        head = repo.head.shorthand
        return head

    def branch_exists(self, repo_path: Path, branch_name: str) -> bool:
        repo = self.get_repo(repo_path)
        return branch_name in repo.branches

    def create_branch(self, repo_path: Path, branch_name: str, source_branch: str) -> None:
        repo = self.get_repo(repo_path)
        if not self.branch_exists(repo_path, branch_name):
            # Get the commit object from the source branch
            source_ref = repo.lookup_branch(source_branch)
            if source_ref is None:
                raise RuntimeError(f"Source branch '{source_branch}' not found")
            commit = repo.get(source_ref.target)
            repo.create_branch(branch_name, commit)

    async def get_working_directory_status(
        self, repo_path: Path, main_repo_path: Path | None = None
    ) -> tuple[list[str], list[str]]:
        """Get working directory status using fastest available method."""
        # For now, use a simple fallback implementation
        # TODO: Implement DaemonStatusChecker for better performance
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
            # Expected errors: repository access issues, corrupted repository, permission problems
            logging.warning(f"Failed to get working directory status for {repo_path}: {e}")
            return [], []

    def get_repo_root(self, cwd: Path | None = None) -> Path:
        repo = self.get_repo(cwd or Path.cwd())
        return Path(repo.workdir).resolve()

    def get_commit_count_between(self, repo_path: Path, rev_a: str, rev_b: str) -> int:
        repo = self.get_repo(repo_path)
        ahead, behind = repo.ahead_behind(rev_b, rev_a)
        return ahead if rev_a == rev_b else (ahead + behind)

    def get_commit_info(self, repo_path: Path, ref: str) -> dict[str, str]:
        repo = self.get_repo(repo_path)
        try:
            # Resolve reference to commit object
            resolved = repo.resolve_refish(ref)
            commit = resolved[0]
        except KeyError as e:
            raise RuntimeError(f"Cannot get commit object for {ref}: {e}") from e

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

    def verify_ref_exists(self, repo_path: Path, ref: str) -> str:
        try:
            repo = self.get_repo(repo_path)
            # Use pygit2 API to resolve the reference
            resolved = repo.resolve_refish(ref)
            return str(resolved[0].id)
        except KeyError as e:
            # Reference does not exist
            raise RuntimeError(f"Reference does not exist: {ref}") from e
        except Exception as e:
            # Don't assume unknown errors mean "reference doesn't exist"
            raise RuntimeError(f"Failed to verify reference {ref}: {e}") from e

    def get_status_porcelain(self, repo_path: Path) -> str:
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
            raise RuntimeError(f"Git status failed for {repo_path}: {e}") from e
