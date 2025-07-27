"""Pure business logic for worktree operations - no I/O, no formatting."""

import asyncio
import concurrent.futures
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..shared.git_interface import (
    CannotCreateWorktree,
    CannotDeleteWorktree,
    GitError,
    GitTimeoutError,
    NoSuchRef,
    WorktreeError,
    WorktreeInfo,
    WorktreeStatus,
)
from ..shared.github_models import PRInfo
from ..shared.models import CommitInfo, ProcessInfo

if TYPE_CHECKING:
    from ..shared.git_interface import GitInterface
    from .github_client import GitHubInterface


class WorktreeService:
    """Pure business logic for worktree operations."""

    def __init__(self, git: "GitInterface", github: "GitHubInterface"):
        self.git = git
        self.github = github

    def list_worktrees(self, config) -> list[tuple[str, Path, bool]]:
        """List all managed worktrees with their existence status."""
        parsed_worktrees = self.git.parse_worktree_list(self.git.worktree_list())
        worktrees = []

        for path, branch in parsed_worktrees:
            if self._is_managed_worktree(path, config):
                worktrees.append((path.name, path, path.exists()))

        return worktrees

    def _is_managed_worktree(self, path: Path, config) -> bool:
        """Check if this worktree should be managed by our tool."""
        # Skip the main repo
        if path.resolve() == config.main_repo_resolved.resolve():
            return False

        # Only include worktrees in our managed directory
        if not path.is_relative_to(config.worktrees_dir_resolved):
            return False

        # Filter out hidden worktrees using configurable patterns
        return not any(path.name.startswith(pattern) for pattern in config.hidden_worktree_patterns)

    def _create_worktree_status(
        self, name: str, path: Path, branch: str, default_branch: str
    ) -> WorktreeStatus:
        """Create status for a single worktree."""
        # Check if branch still exists
        try:
            self.git.verify_branch_exists(branch)
        except NoSuchRef as e:
            raise RuntimeError(f"Stale worktree {name}: branch {branch} was deleted") from e

        # Get ahead/behind counts
        ahead_count = self.git.rev_count(default_branch, branch)
        behind_count = self.git.rev_count(branch, default_branch)

        # Get commit info and working directory status
        commit_info = self._get_commit_info(branch)
        # Note: Working directory status would need to be fetched separately for sync operation
        dirty_files, untracked_files = [], []

        return WorktreeStatus(
            name=name,
            branch=branch,
            ahead=ahead_count,
            behind=behind_count,
            dirty_files=dirty_files,
            untracked_files=untracked_files,
            default_branch=default_branch,
            commit_info=commit_info,
        )

    def _get_commit_info(self, branch_name: str) -> CommitInfo | None:
        """Get commit information for a branch."""
        try:
            commit_data = self.git.log_format(branch_name, "%H|%s|%an|%ai")
            hash_str, message, author, date_str = commit_data.split("|", 3)

            date = datetime.fromisoformat(date_str.replace(" ", "T"))

            return CommitInfo(
                last_commit=hash_str,
                last_commit_message=message,
                last_commit_author=author,
                last_commit_date=date,
            )
        except (ValueError, GitError) as e:
            # Expected errors: invalid date format, git command failures
            logging.warning(f"Failed to get commit info for branch {branch_name}: {e}")
            return None

    async def _get_working_directory_status(
        self, worktree_path: Path, main_repo: Path = None
    ) -> tuple[list[str], list[str]]:
        """Get working directory status for a worktree."""
        try:
            from .git_manager import GitRepositoryManager

            git_repo_manager = GitRepositoryManager()
            return await git_repo_manager.get_working_directory_status(worktree_path, main_repo)
        except (RuntimeError, OSError) as e:
            # Expected errors: repository access issues, file system problems
            logging.warning(f"Failed to get working directory status for {worktree_path}: {e}")
            return [], []

    async def _create_main_repo_status(
        self, name: str, path: Path, branch: str, default_branch: str
    ) -> WorktreeStatus:
        """Create status for main repository."""
        # Main repo has no ahead/behind counts
        ahead_count = 0
        behind_count = 0

        # Get commit info and working directory status
        commit_info = self._get_commit_info("HEAD")
        dirty_files, untracked_files = await self._get_working_directory_status(path)

        return WorktreeStatus(
            name=name,
            branch=branch,
            ahead=ahead_count,
            behind=behind_count,
            dirty_files=dirty_files,
            untracked_files=untracked_files,
            default_branch=default_branch,
            commit_info=commit_info,
        )

    def _create_error_status(
        self, name: str, branch: str, error_msg: str, default_branch: str
    ) -> WorktreeStatus:
        """Create error status for a worktree."""
        return WorktreeStatus(
            name=name,
            branch=branch,
            ahead=0,
            behind=0,
            dirty_files=[],
            untracked_files=[],
            default_branch=default_branch,
            commit_info=None,
            error=error_msg,
        )

    def create_worktree(self, config, name: str, source_worktree: Path | None = None) -> Path:
        """Create a new worktree."""
        from ..shared.error_handling import ErrorContext, validate_worktree_name
        from .git_manager import GitRepositoryManager

        validate_worktree_name(name)
        worktree_path = config.worktrees_dir_resolved / name

        if worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' already exists at {worktree_path}")

        # Ensure worktrees directory exists
        config.worktrees_dir_resolved.mkdir(parents=True, exist_ok=True)

        with ErrorContext("create_worktree", name):
            branch_name = f"{config.branch_prefix}{name}"

            # Get default branch and create branch if needed
            git_repo_manager = GitRepositoryManager()
            default_branch = git_repo_manager.get_default_branch(config.main_repo_resolved)
            git_repo_manager.create_branch(config.main_repo_resolved, branch_name, default_branch)

            # Create worktree
            self.git.worktree_add(str(worktree_path), branch_name)

            # Hydrate with dirty state if source provided
            if source_worktree:
                if not source_worktree.exists():
                    raise RuntimeError(f"Source worktree does not exist: {source_worktree}")
                self._hydrate_worktree(source_worktree, worktree_path)

            return worktree_path

    async def remove_worktree(self, config, name: str, force: bool = False) -> None:
        """Remove a worktree."""
        worktree_path = config.worktrees_dir_resolved / name

        if not worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' does not exist at {worktree_path}")

        # Check for running processes unless forced
        if not force:
            processes = self._get_processes_in_directory(worktree_path)
            if processes:
                proc_strings = [f"PID {p.pid} ({p.name})" for p in processes]
                raise RuntimeError(
                    f"Worktree is in use by: {', '.join(proc_strings)}\nUse --force to remove anyway"
                )

        # Check for uncommitted changes
        if not force:
            dirty_files, untracked_files = await self._get_working_directory_status(worktree_path)
            if dirty_files or untracked_files:
                raise RuntimeError(
                    f"Worktree '{name}' has uncommitted changes. Use --force to remove anyway"
                )

        # Remove worktree
        self.git.worktree_remove(str(worktree_path), force=force)

        # Clean up directory if it still exists
        if worktree_path.exists():
            import shutil

            shutil.rmtree(worktree_path)

    def get_worktree_path(self, config, name: str) -> Path:
        """Get path for a worktree by name."""
        return config.worktrees_dir / name

    def require_worktree_exists(self, config, name: str) -> Path:
        """Require that a worktree exists and return its path."""
        worktree_path = self.get_worktree_path(config, name)
        if not worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' does not exist")
        return worktree_path

    def get_current_worktree_info(self, config) -> tuple[Path | None, str | None]:
        """Get current worktree information."""
        import os
        from pathlib import Path

        # Get current directory
        cwd = Path.cwd().resolve()

        try:
            # Try to find git repo root
            repo_root = self.git.repo_root(cwd=cwd)

            # Check if we're in a worktree (not the main repo)
            if repo_root != config.main_repo_resolved:
                # Calculate relative path within the worktree
                try:
                    rel_path = cwd.relative_to(repo_root)
                except ValueError:
                    rel_path = Path(".")
                return repo_root, str(rel_path) if rel_path != Path(".") else None

            return None, None
        except (GitError, OSError) as e:
            # Expected errors: not in a git repo, file system issues
            logging.debug(f"Could not determine current worktree info: {e}")
            return None, None

    def resolve_path(self, config, worktree_name: str | None, path_spec: str) -> Path:
        """Resolve a path specification within a worktree."""
        if worktree_name:
            # Path in specified worktree
            target_path = self.require_worktree_exists(config, worktree_name)
        else:
            # Path in current worktree
            current_wt, _ = self.get_current_worktree_info(config)
            if not current_wt:
                raise RuntimeError("Not in a worktree")
            target_path = current_wt

        if path_spec.startswith("/"):
            # Absolute path from worktree root
            return target_path / path_spec[1:]
        elif path_spec.startswith("./"):
            # Relative to current position in worktree
            current_wt, rel_path = self.get_current_worktree_info(config)
            if not current_wt:
                raise RuntimeError("Not in a worktree")
            base_path = current_wt / (rel_path or "")
            return base_path / path_spec[2:]
        else:
            raise RuntimeError("Path must start with / (absolute) or ./ (relative)")

    def emit_cd_command(self, dest_repo: Path, config) -> None:
        """Emit a cd command for shell execution."""
        import shlex

        # Try to preserve relative path when switching between worktrees
        current_wt, rel_path = self.get_current_worktree_info(config)

        if rel_path and current_wt:
            # Path preservation: if you're in feature-a/src/components/,
            # try to land in feature-b/src/components/ when switching to feature-b
            dest_subdir = dest_repo / rel_path

            # Walk up the directory tree until we find a path that exists
            final_dest = dest_subdir
            while not final_dest.exists() and final_dest != dest_repo:
                final_dest = final_dest.parent

            dest_repo = final_dest

        from ..shared.shell_utils import emit_command

        emit_command(f"cd {shlex.quote(str(dest_repo))}")

    def _hydrate_worktree(self, src: Path, dst: Path) -> None:
        """Hydrate worktree with files from source."""
        dst.mkdir(parents=True, exist_ok=True)

        # Skip if source is empty
        if not any(src.iterdir()):
            return

        from ..shared.copy_strategies import get_copy_strategy

        strategy = get_copy_strategy()
        strategy.copy(src, dst)

    def _get_processes_in_directory(self, directory: Path) -> list:
        """Get processes running in a directory."""
        import psutil

        from ..shared.models import ProcessInfo

        procs = []
        for proc in psutil.process_iter(["pid", "name", "cwd"]):
            try:
                cwd = proc.info.get("cwd")
                if cwd and Path(cwd).is_relative_to(directory):
                    procs.append(ProcessInfo(pid=proc.info["pid"], name=proc.info["name"]))
                    continue
                for fl in proc.open_files():
                    if fl.path and Path(fl.path).is_relative_to(directory):
                        procs.append(ProcessInfo(pid=proc.pid, name=proc.name()))
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    async def get_all_worktree_status_daemon(
        self, config, daemon_client
    ) -> dict[str, WorktreeStatus]:
        """Get comprehensive status for all worktrees using daemon."""
        if daemon_client is None:
            raise RuntimeError("Daemon client is required for status operations")

        # Single comprehensive daemon RPC call for all status data
        return await daemon_client.get_all_worktree_status()

    def get_sorted_worktree_items(
        self, all_status: dict[str, WorktreeStatus], config
    ) -> list[tuple[str, WorktreeStatus]]:
        """Sort worktree status items for display."""
        from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME
        from .git_manager import GitRepositoryManager

        # Get the actual default branch from git config
        git_repo_manager = GitRepositoryManager()
        default_branch = git_repo_manager.get_default_branch(config.main_repo_resolved)

        def sort_key(item):
            name, status = item
            if status.error:
                return (2, name)  # Errors last
            # Always prioritize the default branch
            if name == MAIN_WORKTREE_DISPLAY_NAME or status.branch == default_branch:
                return (0, "default")  # default branch always first
            else:
                return (1, name)  # others alphabetically

        return sorted(all_status.items(), key=sort_key)

    async def get_single_worktree_status_daemon(
        self, config, worktree_name: str, daemon_client=None
    ) -> tuple[WorktreeStatus, dict[str, PRInfo]]:
        """Get status for a specific worktree using daemon."""
        # Verify the worktree exists
        self.require_worktree_exists(config, worktree_name)

        # Get status for all worktrees and find the one we want
        all_status = await self.get_all_worktree_status_daemon(config, daemon_client)

        if worktree_name not in all_status:
            raise RuntimeError(f"Could not get status for worktree '{worktree_name}'")

        status = all_status[worktree_name]

        # Extract PR info from daemon-provided data
        pr_results = {}
        if status.pr_info:
            pr_results[status.branch] = status.pr_info

        return status, pr_results

    def get_github_pr_status_single(self, branch_name: str) -> PRInfo:
        """Get PR status for a single branch."""
        prs = self.github.pr_search(branch_name)
        if not prs:
            return PRInfo(branch=branch_name)
        pr = prs[0]
        return PRInfo(
            branch=branch_name,
            pr_data=PRData(pr_number=pr.number, pr_state=pr.state),
        )

    async def show_worktree_status(
        self,
        config,
        daemon_client,
        formatter,
        worktree_name: str | None = None,
    ) -> None:
        """Show worktree status - single worktree or all worktrees."""
        if worktree_name:
            await self._show_single_worktree_status(config, daemon_client, formatter, worktree_name)
        else:
            await self._show_all_worktrees_status(config, daemon_client, formatter)

    async def _show_single_worktree_status(
        self, config, daemon_client, formatter, worktree_name: str
    ) -> None:
        """Show status for a single worktree."""
        self.require_worktree_exists(config, worktree_name)

        all_status = await self.get_all_worktree_status_daemon(config, daemon_client)
        status = all_status.get(worktree_name)

        if not status:
            import click

            click.echo(f"❌ No status available for '{worktree_name}'")
            return

        formatter.render_worktree_status_single(worktree_name, status, status.pr_info)

    async def _show_all_worktrees_status(self, config, daemon_client, formatter) -> None:
        """Show status for all worktrees."""
        all_status = await self.get_all_worktree_status_daemon(config, daemon_client)

        if not all_status:
            import click

            click.echo("🤷 No worktrees found")
            return

        sorted_items = self.get_sorted_worktree_items(all_status, config)

        formatter.render_worktree_status_all(sorted_items)
