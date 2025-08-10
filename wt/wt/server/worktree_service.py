"""Pure business logic for worktree operations - no I/O, no formatting."""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..shared.github_models import PRInfo
from ..shared.models import CommitInfo, ProcessInfo
from ..shared.protocol import StatusResult
from .git_manager import (
    GitError,
)

if TYPE_CHECKING:
    from .git_manager import GitManager
    from .github_client import GitHubInterface


logger = logging.getLogger(__name__)


class WorktreeService:
    """Pure business logic for worktree operations."""

    def __init__(self, git_manager: "GitManager", github: "GitHubInterface"):
        self.git_manager = git_manager
        self.github = github

    def list_worktrees(self, config) -> list[tuple[str, Path, bool]]:
        """List all managed worktrees with their existence status."""
        worktree_infos = self.git_manager.list_worktrees()
        worktrees = []

        for info in worktree_infos:
            if self._is_managed_worktree(info.path, config) and not info.is_main:
                worktrees.append((info.path.name, info.path, info.exists))

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
        return not any(
            path.name.startswith(pattern) for pattern in config.hidden_worktree_patterns
        )

    # Note: This method was deleted as part of WorktreeStatus compatibility cleanup.
    # Status creation is now handled by the daemon using proper protocol types.

    def _get_commit_info(self, branch_name: str) -> CommitInfo | None:
        """Get commit information for a branch."""
        try:
            commit_data = self.git_manager.log_format(branch_name, "%H|%s|%an|%ai")
            hash_str, message, author, date_str = commit_data.split("|", 3)

            date = datetime.fromisoformat(date_str.replace(" ", "T"))

            return CommitInfo(
                last_commit=hash_str,
                last_commit_message=message,
                last_commit_author=author,
                last_commit_date=date,
            )
        except (ValueError, GitError) as e:
            # Let callers handle git errors appropriately instead of masking them
            raise GitError(
                f"Failed to get commit info for branch {branch_name}: {e}",
            ) from e

    async def _get_working_directory_status(
        self,
        worktree_path: Path,
    ) -> tuple[list[str], list[str]]:
        """Get working directory status for a worktree."""
        try:
            return await self.git_manager.get_working_directory_status(worktree_path)
        except Exception as e:
            # Let callers handle git errors appropriately instead of masking them
            raise RuntimeError(
                f"Failed to get working directory status for {worktree_path}: {e}",
            ) from e

    # Note: This method was deleted as part of WorktreeStatus compatibility cleanup.
    # Status creation is now handled by the daemon using proper protocol types.

    # Note: This method was deleted as part of WorktreeStatus compatibility cleanup.
    # Error handling is now part of the daemon's StatusResult protocol.

    def create_worktree(
        self,
        config,
        name: str,
        source_worktree: Path | None = None,
    ) -> Path:
        """Create a new worktree."""
        from ..shared.error_handling import ErrorContext, validate_worktree_name

        validate_worktree_name(name)
        worktree_path = config.worktrees_dir_resolved / name

        if worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' already exists at {worktree_path}")

        # Ensure worktrees directory exists
        config.worktrees_dir_resolved.mkdir(parents=True, exist_ok=True)

        with ErrorContext("create_worktree", name):
            branch_name = f"{config.branch_prefix}{name}"

            # Use configured upstream branch as source for new branches
            self.git_manager.create_branch(
                branch_name,
                config.upstream_branch,
                config.main_repo_resolved,
            )

            # Create worktree
            self.git_manager.worktree_add(str(worktree_path), branch_name)

            # Hydrate with dirty state if source provided
            if config.hydrate_worktrees:
                if source_worktree:
                    if not source_worktree.exists():
                        raise RuntimeError(
                            f"Source worktree does not exist: {source_worktree}",
                        )
                    self._hydrate_worktree(config, source_worktree, worktree_path)
                else:
                    repo = self.git_manager.get_repo(worktree_path)
                    try:
                        repo.set_head(f"refs/heads/{branch_name}")
                    except Exception:
                        pass
                    repo.checkout_head(strategy=getattr(__import__('pygit2'), 'GIT_CHECKOUT_FORCE', 0))

            logger.info(
                f"Post-creation script configured: {config.post_creation_script}",
            )
            if config.post_creation_script:
                script = config.post_creation_script
                if not script.exists() or not script.is_file():
                    raise RuntimeError(
                        f"Post-creation script configured but not found or not a file: {script}",
                    )
                logger.info(
                    f"Executing post-creation script for worktree: {worktree_path}",
                )
                WorktreeService.execute_post_creation_script(
                    str(script),
                    worktree_path,
                )
            else:
                logger.info("No post-creation script configured, skipping")

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
                    f"Worktree is in use by: {', '.join(proc_strings)}\nUse --force to remove anyway",
                )

        # Check for uncommitted changes
        if not force:
            dirty_files, untracked_files = await self._get_working_directory_status(
                worktree_path,
            )
            if dirty_files or untracked_files:
                raise RuntimeError(
                    f"Worktree '{name}' has uncommitted changes. Use --force to remove anyway",
                )

        # Remove worktree
        self.git_manager.worktree_remove(str(worktree_path), force=force)

        # Clean up directory if it still exists
        if worktree_path.exists():
            import shutil

            shutil.rmtree(worktree_path)

    def get_worktree_path(self, config, name: str) -> Path:
        """Get path for a worktree by name."""
        return config.worktrees_dir_resolved / name

    def require_worktree_exists(self, config, name: str) -> Path:
        """Require that a worktree exists and return its path."""
        worktree_path = self.get_worktree_path(config, name)
        if not worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' does not exist")
        return worktree_path

    def get_current_worktree_info(self, config) -> tuple[Path | None, str | None]:
        """Get current worktree information."""
        from pathlib import Path

        # Get current directory
        cwd = Path.cwd().resolve()

        try:
            # Try to find git repo root
            repo_root = self.git_manager.repo_root(cwd=cwd)

            # Check if we're in a worktree (not the main repo)
            if repo_root != config.main_repo_resolved:
                # Calculate relative path within the worktree
                try:
                    rel_path = cwd.relative_to(repo_root)
                except ValueError:
                    rel_path = Path()
                return repo_root, str(rel_path) if rel_path != Path() else None

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
        if path_spec.startswith("./"):
            # Relative to current position in worktree
            current_wt, rel_path = self.get_current_worktree_info(config)
            if not current_wt:
                raise RuntimeError("Not in a worktree")
            base_path = current_wt / (rel_path or "")
            return base_path / path_spec[2:]
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

        from ..client.shell_utils import emit_command

        emit_command(f"cd {shlex.quote(str(dest_repo))}")

    def _hydrate_worktree(self, config, src: Path, dst: Path) -> None:
        """Hydrate worktree with files from source."""
        dst.mkdir(parents=True, exist_ok=True)

        # Skip if source is empty
        if not any(src.iterdir()):
            return

        from .copy_strategies import get_copy_strategy

        strategy = get_copy_strategy(config.cow_method)
        strategy.copy(src, dst)

    @staticmethod
    def execute_post_creation_script(script_path: str, worktree_path: Path) -> dict:
        import logging
        import subprocess

        logger = logging.getLogger(__name__)
        logger.info(
            f"Starting post-creation script execution: script={script_path}, worktree={worktree_path}",
        )

        script = Path(script_path).expanduser().resolve()
        logger.info(f"Resolved script path: {script}")

        if not script.exists():
            logger.warning(f"Post-creation script not found: {script}")
            return {
                "ran": False,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "not_found",
            }

        if not script.is_file():
            logger.warning(f"Post-creation script is not a file: {script}")
            return {
                "ran": False,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "not_file",
            }

        if not script.stat().st_mode & 0o111:
            logger.warning(f"Post-creation script is not executable: {script}")

        logger.info(f"Executing post-creation script: {script} {worktree_path}")
        try:
            result = subprocess.run(
                [str(script), str(worktree_path)],
                check=False,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.warning(
                    f"Post-creation script failed (exit {result.returncode}): {script}\n"
                    f"stdout: {result.stdout}\n"
                    f"stderr: {result.stderr}",
                )
            else:
                logger.info(f"Post-creation script completed successfully: {script}")
                if result.stdout:
                    logger.info(f"Post-creation script stdout: {result.stdout}")
                if result.stderr:
                    logger.info(f"Post-creation script stderr: {result.stderr}")
            return {
                "ran": True,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "error": None,
            }
        except subprocess.TimeoutExpired:
            logger.error(f"Post-creation script timed out: {script}", exc_info=True)
            return {
                "ran": True,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "timeout",
            }
        except Exception as e:
            logger.error(
                f"Error executing post-creation script {script}: {e}",
                exc_info=True,
            )
            return {
                "ran": True,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": str(e),
            }

    def _get_processes_in_directory(self, directory: Path) -> list:
        """Get processes running in a directory."""
        import psutil

        procs = []
        for proc in psutil.process_iter(["pid", "name", "cwd"]):
            try:
                cwd = proc.info.get("cwd")
                if cwd and Path(cwd).is_relative_to(directory):
                    procs.append(
                        ProcessInfo(pid=proc.info["pid"], name=proc.info["name"]),
                    )
                    continue
                for fl in proc.open_files():
                    if fl.path and Path(fl.path).is_relative_to(directory):
                        procs.append(ProcessInfo(pid=proc.pid, name=proc.name()))
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    # Note: This method was moved to handlers.py for client-side sorting.

    async def get_single_worktree_status_daemon(
        self,
        config,
        worktree_name: str,
        daemon_client=None,
    ) -> tuple[StatusResult, dict[str, PRInfo]]:
        """Get status for a specific worktree using daemon."""
        # Verify the worktree exists
        self.require_worktree_exists(config, worktree_name)

        # Get status for all worktrees and find the one we want
        all_status = await daemon_client.get_status([])

        # Find the worktree by name
        status = None
        for result in all_status.results.values():
            if result.name == worktree_name:
                status = result
                break

        if not status:
            raise RuntimeError(f"Could not get status for worktree '{worktree_name}'")

        # Extract PR info from daemon-provided data
        pr_results = {}
        if status.pr_info:
            pr_results[status.branch_name] = status.pr_info

        return status, pr_results

    def get_github_pr_status_single(self, branch_name: str) -> PRInfo:
        """Get PR status for a single branch."""
        prs = self.github.pr_search(branch_name)
        if not prs:
            return PRInfo(branch=branch_name)
        pr = prs[0]
        from ..shared.github_models import PRData

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
            await self._show_single_worktree_status(
                config,
                daemon_client,
                formatter,
                worktree_name,
            )
        else:
            await self._show_all_worktrees_status(config, daemon_client, formatter)

    async def _show_single_worktree_status(
        self,
        config,
        daemon_client,
        formatter,
        worktree_name: str,
    ) -> None:
        """Show status for a single worktree."""
        self.require_worktree_exists(config, worktree_name)

        all_status = await daemon_client.get_status([])

        # Find the worktree by name in the results
        status = None
        for result in all_status.results.values():
            if result.name == worktree_name:
                status = result
                break

        if not status:
            import click

            click.echo(f"❌ No status available for '{worktree_name}'")
            return

        formatter.render_worktree_status_single(worktree_name, status, status.pr_info)

    async def _show_all_worktrees_status(
        self,
        config,
        daemon_client,
        formatter,
    ) -> None:
        """Show status for all worktrees."""
        all_status = await daemon_client.get_status([])

        if not all_status:
            import click

            click.echo("🤷 No worktrees found")
            return

        # Sort results for display
        from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME

        def sort_key(item):
            wtid, status = item
            # Always prioritize the main worktree
            if status.name == MAIN_WORKTREE_DISPLAY_NAME:
                return (0, "main")  # main worktree always first
            return (1, status.name)  # others alphabetically

        sorted_items = sorted(all_status.results.items(), key=sort_key)
        # Convert to (name, status) tuples for display
        display_items = [(result.name, result) for wtid, result in sorted_items]

        formatter.render_worktree_status_all(display_items)
