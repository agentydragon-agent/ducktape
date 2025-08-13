"""Pure business logic for worktree operations - no I/O, no formatting."""

import asyncio
import contextlib
import logging
import shutil
import inspect
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

import psutil
import pygit2

from ..shared.error_handling import ErrorContext, validate_worktree_name
from ..shared.github_models import PRData, PRInfo
from ..shared.models import CommitInfo, ProcessInfo
from .copy_strategies import get_copy_strategy
from .git_manager import GitError, GitManager, WorktreeCreateError, WorktreeDeleteError

if TYPE_CHECKING:
    from .github_client import GitHubInterface


logger = logging.getLogger(__name__)


class WorktreeService:
    """Pure business logic for worktree operations."""

    def __init__(self, git_manager: GitManager, github: "GitHubInterface"):
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
        if path.resolve() == config.main_repo.resolve():
            return False

        # Only include worktrees in our managed directory
        if not path.is_relative_to(config.worktrees_dir):
            return False

        # Filter out hidden worktrees using configurable patterns
        return not any(
            path.name.startswith(pattern) for pattern in config.hidden_worktree_patterns
        )

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

    def _require_post_creation_script_valid(self, config) -> None:
        if config.post_creation_script:
            script = config.post_creation_script
            if not script.exists() or not script.is_file():
                raise FileNotFoundError(f"Post-creation script {script} is not a file")

    def _wtid_to_path(self, config, wtid: "WorktreeID") -> Path:
        from .worktree_ids import wtid_to_path
        return wtid_to_path(config, wtid)

    def create_worktree(
        self,
        config,
        name: str,
        source_worktree: Path | None = None,
        source_branch: str | None = None,
    ) -> Path:
        """Create a new worktree."""
        validate_worktree_name(name)
        self._require_post_creation_script_valid(config)
        worktree_path = config.worktrees_dir / name

        if worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' already exists at {worktree_path}")

        # Ensure worktrees directory exists
        config.worktrees_dir.mkdir(parents=True, exist_ok=True)

        with ErrorContext("create_worktree", name):
            branch_name = f"{config.branch_prefix}{name}"

            # Use provided source_branch if given; otherwise configured upstream
            self.git_manager.create_branch(
                branch_name,
                source_branch or config.upstream_branch,
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
                    import pygit2 as _pygit2
                    repo = _pygit2.Repository(str(worktree_path))
                    repo.set_head(f"refs/heads/{branch_name}")
                    repo.checkout_head(strategy=_pygit2.GIT_CHECKOUT_FORCE)
            else:
                logger.info("Not hydrating worktree.")
            return worktree_path

    def get_worktree_path(self, config, name: str) -> Path:
        """Get path for a worktree by name."""
        return config.worktrees_dir / name

    async def remove_worktree(self, config, name: str, force: bool = False) -> None:
        """Remove a worktree by name and clean up its directory."""
        validate_worktree_name(name)
        worktree_path = self.get_worktree_path(config, name)
        if not worktree_path.exists():
            return
        self.git_manager.worktree_remove(str(worktree_path), force=force)
        try:
            shutil.rmtree(worktree_path, ignore_errors=True)
        except Exception:
            pass

    def require_worktree_exists(self, config, name: str) -> Path:
        """Require that a worktree exists and return its path."""
        worktree_path = self.get_worktree_path(config, name)
        if not worktree_path.exists():
            raise RuntimeError(f"Worktree '{name}' does not exist")
        return worktree_path


    def _hydrate_worktree(self, config, src: Path, dst: Path) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        get_copy_strategy(config.cow_method).copy(src, dst)


    @staticmethod
    async def run_post_creation_script(
        script_path: str,
        worktree_path: Path,
        sink: Callable[[str, str], Awaitable[None]] | Callable[[str, str], None] | None = None,
        timeout: float = 60.0,
    ) -> dict:
        logging.getLogger(__name__)
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

        if sink is None:
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return {
                    "ran": True,
                    "exit_code": proc.returncode,
                    "stdout": stdout.decode(errors="replace") if stdout else None,
                    "stderr": stderr.decode(errors="replace") if stderr else None,
                    "error": None,
                }
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    proc.kill()
                    await proc.wait()
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
                    result = sink(name, text)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logging.getLogger(__name__).debug("hook sink failed", exc_info=True)

        t1 = (
            asyncio.create_task(_forward(proc.stdout, "stdout"))
            if proc.stdout
            else None
        )
        t2 = (
            asyncio.create_task(_forward(proc.stderr, "stderr"))
            if proc.stderr
            else None
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
            return {
                "ran": True,
                "exit_code": None,
                "stdout": None,
                "stderr": None,
                "error": "timeout",
            }
        if t1:
            await t1
        if t2:
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
                        ProcessInfo(pid=proc.pid, name=proc.name()),
                    )
                    continue
                for fl in proc.open_files():
                    if fl.path and Path(fl.path).is_relative_to(directory):
                        procs.append(ProcessInfo(pid=proc.pid, name=proc.name()))
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs


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
