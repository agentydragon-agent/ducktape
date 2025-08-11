"""Pure business logic for worktree operations - no I/O, no formatting."""

import json
import logging
import asyncio
import contextlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
import psutil
import pygit2

from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from ..shared.error_handling import ErrorContext, validate_worktree_name
from ..shared.github_models import PRInfo, PRData
from ..shared.models import CommitInfo, ProcessInfo
from ..shared.protocol import StatusResult
from .copy_strategies import get_copy_strategy
from .git_manager import GitError

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
        source_branch: str | None = None,
    ) -> Path:
        """Create a new worktree."""
        validate_worktree_name(name)
        worktree_path = config.worktrees_dir_resolved / name

        if worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' already exists at {worktree_path}")

        # Ensure worktrees directory exists
        config.worktrees_dir_resolved.mkdir(parents=True, exist_ok=True)

        with ErrorContext("create_worktree", name):
            branch_name = f"{config.branch_prefix}{name}"

            # Use provided source_branch if given; otherwise configured upstream
            self.git_manager.create_branch(
                branch_name,
                source_branch or config.upstream_branch,
                config.main_repo_resolved,
            )

            # Create worktree
            self.git_manager.worktree_add(str(worktree_path), branch_name)

            # Hydrate with dirty state if source provided
            if config.hydrate_worktrees:
                if source_worktree:
                    logger.info(
                        f"Hydrating new worktree in {worktree_path} from {source_worktree}.",
                    )
                    if not source_worktree.exists():
                        raise RuntimeError(
                            f"Source worktree does not exist: {source_worktree}",
                        )
                    self._hydrate_worktree(config, source_worktree, worktree_path)
                else:
                    logger.info(
                        f"Hydrating new worktree in {worktree_path} by checking out {branch_name}.",
                    )
                    repo = self.git_manager.get_repo(worktree_path)
                    repo.set_head(f"refs/heads/{branch_name}")
                    repo.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)
            else:
                logger.info("Not hydrating worktree.")

            logger.info(
                f"Post-creation script configured: {config.post_creation_script}",
            )
            logger.info("Post-creation scripts are executed by the daemon during RPC; skipping here")

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


    def _hydrate_worktree(self, config, src: Path, dst: Path) -> None:
        """Hydrate worktree with files from source."""
        dst.mkdir(parents=True, exist_ok=True)

        # Skip if source is empty
        if not any(src.iterdir()):
            return

        strategy = get_copy_strategy(config.cow_method)
        strategy.copy(src, dst)


    @staticmethod
    async def run_post_creation_script(
        script_path: str,
        worktree_path: Path,
        writer=None,
        timeout: float = 60.0,
    ) -> dict:
        logger = logging.getLogger(__name__)
        script = Path(script_path).expanduser().resolve()
        if not script.exists() or not script.is_file():
            return {
                "ran": False,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "not_found" if not script.exists() else "not_file",
            }

        proc = await asyncio.create_subprocess_exec(
            str(script),
            f"--worktree_root={worktree_path}",
            f"--worktree_name={worktree_path.name}",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if writer is None:
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return {
                    "ran": True,
                    "exit_code": proc.returncode,
                    "stdout": stdout.decode(errors="replace") if stdout else None,
                    "stderr": stderr.decode(errors="replace") if stderr else None,
                    "error": None,
                }
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    proc.kill(); await proc.wait()
                return {
                    "ran": True,
                    "exit_code": None,
                    "stdout": None,
                    "stderr": None,
                    "error": "timeout",
                }

        stdout_buf: list[str] = []
        stderr_buf: list[str] = []

        async def _forward(stream, name):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace")
                    if name == "stdout":
                        stdout_buf.append(text)
                    else:
                        stderr_buf.append(text)
                    try:
                        event = {"event": "hook_output", "stream": name, "data": text}
                        writer.write((json.dumps(event) + "\n").encode())
                        await writer.drain()
                    except Exception:
                        pass
            except Exception:
                pass

        t1 = (
            asyncio.create_task(_forward(proc.stdout, "stdout")) if proc.stdout else None
        )
        t2 = (
            asyncio.create_task(_forward(proc.stderr, "stderr")) if proc.stderr else None
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill(); await proc.wait()
            return {
                "ran": True,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "timeout",
            }
        if t1:
            with contextlib.suppress(Exception):
                await t1
        if t2:
            with contextlib.suppress(Exception):
                await t2
        return {
            "ran": True,
            "exit_code": proc.returncode,
            "stdout": "".join(stdout_buf) if stdout_buf else None,
            "stderr": "".join(stderr_buf) if stderr_buf else None,
            "error": None,
        }

    def _get_processes_in_directory(self, directory: Path) -> list:
        """Get processes running in a directory."""
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
            click.echo("🤷 No worktrees found")
            return

        # Sort results for display
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
