"""wt server: handles multiplexing gitstatusd, GitHub and worktree management.

One daemon per main git repository that:
- Auto-discovers worktrees by filesystem scanning
- Manages gitstatusd processes per worktree
- Provides socket-based API for CLI clients
- Handles concurrent requests efficiently
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from ..shared.protocol import (
    CommitInfo,
    ErrorCodes,
    ErrorResponse,
    GitstatusdState,
    PingResult,
    Request,
    Response,
    StatusParams,
    StatusResponse,
    StatusResult,
    TeleportCdThere,
    TeleportDoesNotExist,
    WorktreeCreateParams,
    WorktreeCreateResult,
    WorktreeDeleteParams,
    WorktreeDeleteResult,
    WorktreeGetByNameParams,
    WorktreeGetByNameResult,
    WorktreeIdentifyParams,
    WorktreeIdentifyResult,
    WorktreeListResult,
    WorktreeResolvePathParams,
    WorktreeResolvePathResult,
    WorktreeTeleportTargetParams,
    create_error_response,
    parse_request,
    DaemonHealth,
    DaemonHealthStatus,
    ComponentState,
    ReadinessSummary,
    ComponentsStatus,
    ComponentStatus,
    parse_worktree_id,
    WorktreeInfo as ProtocolWorktreeInfo,
)
from .git_manager import GitManager
from .gitstatusd_client import (
    GitStatusdParseError,
    GitStatusdProtocol,
    GitStatusdRequest,
    GitStatusdValidationError,
    gitstatusd_response_to_legacy_format,
)
from .worktree_ids import make_worktree_id, wtid_to_path
from .worktree_service import WorktreeService
from ..shared.protocol import (
    DaemonHealth,
    DaemonHealthStatus,
    ComponentState,
    ReadinessSummary,
    ComponentsStatus,
    ComponentStatus,
    parse_worktree_id,
    WorktreeInfo as ProtocolWorktreeInfo,
)
from .github_client import GitHubInterface

logger = logging.getLogger(__name__)


def write_startup_handshake(
    success: bool,
    error_message: str = None,
    *,
    redirect_after: bool = True,
    **extra_data,
):
    """Write startup handshake/progress JSON to dedicated pipe FD if provided.

    Args:
        success: Whether startup was successful
        error_message: Error message if startup failed
        redirect_after: If True, redirect stdout to daemon log after writing JSON
        **extra_data: Additional data to include in handshake
    """

    fd_env = os.environ.get("WT_HANDSHAKE_FD")
    handshake_fd = None
    if fd_env and fd_env.isdigit():
        try:
            handshake_fd = int(fd_env)
        except (ValueError, TypeError):
            handshake_fd = None

    handshake_data = {
        "success": success,
        "pid": os.getpid(),
        "timestamp": time.time(),
        **extra_data,
    }

    if not success and error_message:
        handshake_data["error"] = error_message

    payload = (json.dumps(handshake_data) + "\n").encode()
    if handshake_fd is None:
        raise RuntimeError("WT_HANDSHAKE_FD not set; cannot send startup handshake")
    os.write(handshake_fd, payload)

    if redirect_after:
        try:
            from wt.shared.configuration import load_config

            daemon_log = load_config().daemon_dir / "daemon.log"
            log_fd = os.open(
                daemon_log,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            os.dup2(log_fd, 1)
            os.close(log_fd)
        except OSError:
            os.dup2(2, 1)
        logger.info("Startup handshake sent: success=%s", success)
        if not success:
            logger.error("Startup failed: %s", error_message)


@dataclass
class WorktreeGitStatus:
    """Git status result from a single worktree."""

    worktree_path_str: str
    status_result: StatusResult | None
    processing_time_ms: float


def resolve_worktree_name_to_info(name: str, worktree_infos: list) -> object | None:
    """Server authority: resolve user-provided name to worktree info.

    This is the ONLY place where 'main' → main worktree mapping happens.
    All other code should use this function rather than implementing the logic directly.
    """
    for info in worktree_infos:
        if (info.is_main and name == MAIN_WORKTREE_DISPLAY_NAME) or (
            not info.is_main and info.path.name == name
        ):
            return info
    return None


class DebouncedGitHubRefresh:
    """Handles debounced GitHub refresh triggered by .git directory changes + periodic updates."""

    def __init__(
        self,
        worktree_path: Path,
        refresh_callback,
        debounce_delay: float = 5.0,
        periodic_interval: float = 60.0,
    ):
        self.worktree_path = worktree_path
        self.refresh_callback = (
            refresh_callback  # async function to call when refresh needed
        )

        # Configurable timing
        self.debounce_delay = debounce_delay  # seconds to wait after last change
        self.periodic_interval = periodic_interval  # seconds between periodic refreshes

        # State tracking
        self.pending_refresh_task: asyncio.Task | None = None
        self.last_refresh_time = 0.0
        self.pending_files: set[str] = set()

        # File watcher
        self.observer: Observer | None = None
        self.event_handler = GitFileHandler(self)

        # Background tasks
        self.periodic_task: asyncio.Task | None = None
        self.is_running = False

    async def start(self):
        """Start the file watcher and periodic refresh."""
        if self.is_running:
            return

        self.is_running = True

        # Start file watcher
        self._start_file_watcher()

        # Start periodic refresh task
        self.periodic_task = asyncio.create_task(self._periodic_refresh_loop())

        logger.info(f"Started GitHub refresh system for {self.worktree_path}")

    def _start_file_watcher(self):
        """Start watching .git directory for git operation changes."""
        if self.observer:
            return

        self.observer = Observer()

        # Only watch .git directory for git operations (push/pull/commit/etc)
        git_dir = self.worktree_path / ".git"
        if git_dir.exists():
            self.observer.schedule(self.event_handler, str(git_dir), recursive=True)
            logger.debug(f"Watching .git directory: {git_dir}")
        else:
            logger.warning(f"No .git directory found at {git_dir}")

        self.observer.start()

    async def stop(self):
        """Stop the refresh system."""
        self.is_running = False

        # Stop file watcher
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

        # Cancel pending tasks
        if self.pending_refresh_task:
            self.pending_refresh_task.cancel()

        if self.periodic_task:
            self.periodic_task.cancel()

        logger.info(f"Stopped GitHub refresh system for {self.worktree_path}")

    def trigger_refresh(self, reason: str, file_path: str | None = None):
        """Trigger a debounced refresh."""
        current_time = time.time()

        if file_path:
            self.pending_files.add(file_path)

        logger.debug(f"GitHub refresh triggered: {reason} (file: {file_path})")

        # Cancel existing pending refresh
        if self.pending_refresh_task:
            self.pending_refresh_task.cancel()

        # Schedule new debounced refresh
        self.pending_refresh_task = asyncio.create_task(
            self._debounced_refresh(reason, current_time),
        )

    async def _debounced_refresh(self, reason: str, trigger_time: float):
        """Wait for debounce delay, then refresh if no newer triggers."""
        try:
            await asyncio.sleep(self.debounce_delay)

            # Check if we're still the latest refresh request
            if self.pending_refresh_task and not self.pending_refresh_task.done():
                await self._do_refresh(f"debounced: {reason}")

        except asyncio.CancelledError:
            logger.debug(f"Debounced refresh cancelled: {reason}")

    async def _periodic_refresh_loop(self):
        """Background task for periodic GitHub updates."""
        while self.is_running:
            try:
                await asyncio.sleep(self.periodic_interval)

                if self.is_running:
                    current_time = time.time()
                    time_since_last = current_time - self.last_refresh_time

                    # Only do periodic refresh if we haven't refreshed recently
                    if (
                        time_since_last >= self.periodic_interval * 0.8
                    ):  # 80% of interval
                        await self._do_refresh("periodic")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic refresh: {e}", exc_info=True)
                await asyncio.sleep(10)  # Back off on errors

    async def _do_refresh(self, reason: str):
        """Actually perform the GitHub refresh."""
        try:
            start_time = time.time()
            files_changed = list(self.pending_files)
            self.pending_files.clear()

            logger.info(f"Refreshing GitHub data: {reason} (files: {files_changed})")

            # First, try to fetch origin/master to get latest remote info
            fetch_success = await self._fetch_origin_master()

            # Call the refresh callback (typically updates PR cache)
            await self.refresh_callback(reason, files_changed)

            self.last_refresh_time = time.time()
            refresh_time = (self.last_refresh_time - start_time) * 1000

            fetch_status = "with fetch" if fetch_success else "without fetch"
            logger.info(
                f"GitHub refresh completed in {refresh_time:.1f}ms ({fetch_status})",
            )

        except Exception as e:
            logger.error(f"GitHub refresh failed: {e}")

    async def _fetch_origin_master(self) -> bool:
        """Fetch origin/master to get latest remote info. Safe if offline."""
        try:
            logger.debug(f"Fetching origin/master for {self.worktree_path}")

            process = await asyncio.create_subprocess_exec(
                "git",
                "fetch",
                "origin",
                "master",
                cwd=self.worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=10.0,
                )

                if process.returncode == 0:
                    logger.debug("Successfully fetched origin/master")
                    return True
                logger.debug(f"Git fetch failed (offline?): {stderr.decode().strip()}")
                return False

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.debug("Git fetch timed out (slow network?)")
                return False

        except Exception as e:
            logger.debug(f"Git fetch error: {e}")
            return False


class GitFileHandler(FileSystemEventHandler):
    """Handles file system events for git-related files in .git directory."""

    def __init__(self, refresh_system: DebouncedGitHubRefresh):
        self.refresh_system = refresh_system

        # Files that indicate git operations that could affect PR status
        self.watched_patterns = {
            "refs/heads/",  # Branch changes
            "refs/remotes/",  # Remote changes
            "HEAD",  # Branch switches
            "index",  # Staged changes
            "COMMIT_EDITMSG",  # Commits
            "FETCH_HEAD",  # Fetch operations
            "ORIG_HEAD",  # Merge/rebase operations
        }

    def on_modified(self, event):
        if event.is_directory:
            return

        file_path = event.src_path

        # Check if this is a git file we care about
        if self._should_trigger_refresh(file_path):
            reason = f"git file modified: {Path(file_path).name}"
            self.refresh_system.trigger_refresh(reason, file_path)

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path

        if self._should_trigger_refresh(file_path):
            reason = f"git file created: {Path(file_path).name}"
            self.refresh_system.trigger_refresh(reason, file_path)

    def _should_trigger_refresh(self, file_path: str) -> bool:
        """Check if this file change should trigger a GitHub refresh."""
        path_str = str(file_path)

        # Check against patterns
        for pattern in self.watched_patterns:
            if pattern in path_str:
                logger.debug(
                    f"Git file change detected: {path_str} (pattern: {pattern})",
                )
                return True

        return False


class WorktreeInfo:
    """Information about a discovered worktree."""

    def __init__(self, path: Path, name: str):
        self.path = path
        self.name = name
        self.discovered_at = time.time()
        self.last_seen = time.time()

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return isinstance(other, WorktreeInfo) and self.path == other.path


@dataclass
class StatusSnapshot:
    dirty_files: list[str]
    untracked_files: list[str]
    commit_info: dict[str, Any]
    ahead_behind: tuple[int, int]
    branch_name: str
    pr_info: dict[str, Any] | None
    last_updated_at: datetime
    is_cached: bool


@dataclass
class WorktreeRuntime:
    gs_client: "GitstatusdClient"
    pr_service: "PRService"


class GitstatusdClient:
    def __init__(self, worktree_info: WorktreeInfo, config, git_manager: GitManager, error_callback=None):
        self.worktree_info = worktree_info
        self.config = config
        self.git_manager = git_manager
        self.error_callback = error_callback
        self.process: asyncio.subprocess.Process | None = None
        # Cache for working status
        self.cached_working_status: tuple[list[str], list[str]] | None = None
        self.last_updated_at: datetime | None = None
        self._status_updating: bool = False

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        gitstatusd_path = (
            str(self.config.gitstatusd_path)
            if self.config.gitstatusd_path
            else shutil.which("gitstatusd")
        )
        if not gitstatusd_path:
            return
        self.process = await asyncio.create_subprocess_exec(
            gitstatusd_path,
            "--num-threads=8",
            "--max-num-staged=-1",
            "--max-num-unstaged=-1",
            "--max-num-untracked=-1",
            "--max-commit-summary-length=0",
            "--repo-ttl-seconds=3600",
            "--log-level=FATAL",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def stop(self) -> None:
        if not self.process:
            return
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        self.process = None

    @property
    def is_running(self) -> bool:
        return bool(self.process and self.process.returncode is None)

    async def request_working_status(
        self,
    ) -> tuple[list[str], list[str], datetime, bool]:
        # Legacy compatibility: perform a synchronous update of the cache,
        # then return cached values
        await self.update_working_status()
        if self.cached_working_status and self.last_updated_at:
            df, uf = self.cached_working_status
            return df, uf, self.last_updated_at, True
        now = datetime.now()
        return [], [], now, False

    async def update_working_status(self) -> None:
        if not self.process or self.process.returncode is not None:
            await self.start()
        if not self.process or not self.process.stdin or not self.process.stdout:
            self.cached_working_status = ([], [])
            self.last_updated_at = datetime.now()
            return
        if self._status_updating:
            return
        self._status_updating = True
        try:
            request_id = str(uuid.uuid4())[:8]
            gitstatusd_request = GitStatusdRequest(
                request_id=request_id,
                directory_path=str(self.worktree_info.path),
                disable_index_computation=False,
            )
            request_data = gitstatusd_request.to_wire_format()
            self.process.stdin.write(request_data.encode())
            await self.process.stdin.drain()
            response = await asyncio.wait_for(
                self.process.stdout.readuntil(b"\x1e"),
                timeout=2.0,
            )
            response_str = response.decode("utf-8")
            parsed_response = GitStatusdProtocol.parse_response(response_str)
            dirty_files, untracked_files = gitstatusd_response_to_legacy_format(
                parsed_response,
            )
            self.cached_working_status = (dirty_files, untracked_files)
            self.last_updated_at = datetime.now()
        except Exception:
            if not self.last_updated_at:
                self.last_updated_at = datetime.now()
        finally:
            self._status_updating = False

    def get_cached_working_status(self) -> tuple[list[str], list[str], datetime | None, bool]:
        if self.cached_working_status and self.last_updated_at:
            df, uf = self.cached_working_status
            return df, uf, self.last_updated_at, True
        return [], [], None, False


class RepoMetaService:
    def __init__(self, git_manager: GitManager, config):
        self.git_manager = git_manager
        self.config = config

    def compute_meta(
        self,
        worktree_path: Path,
    ) -> tuple[dict[str, Any], tuple[int, int], str]:
        repo = self.git_manager.get_repo(worktree_path)
        branch_name = repo.head.shorthand
        commit_info_data = self.git_manager.get_commit_info("HEAD", worktree_path)
        ahead_behind = (0, 0)
        if worktree_path != self.config.main_repo_resolved:
            try:
                main_repo = self.git_manager.get_repo(self.config.main_repo_resolved)
                ahead, behind = main_repo.ahead_behind(
                    f"refs/heads/{branch_name}",
                    f"refs/heads/{self.config.upstream_branch}",
                )
                ahead_behind = (ahead, behind)
            except Exception:
                ahead_behind = (0, 0)
        return commit_info_data, ahead_behind, branch_name


class PRService:
    def __init__(self, github_interface, config, worktree_info: WorktreeInfo):
        self.github_interface = github_interface
        self.config = config
        self.worktree_info = worktree_info
        self.cached_pr_info: dict[str, Any] | None = None
        self.pr_last_fetched: float | None = None
        self.github_refresh: DebouncedGitHubRefresh | None = None

    async def start(self) -> None:
        if self.github_interface:
            self.github_refresh = DebouncedGitHubRefresh(
                self.worktree_info.path,
                self._refresh_github_cache,
                debounce_delay=self.config.github_debounce_delay.total_seconds(),
                periodic_interval=self.config.github_periodic_interval.total_seconds(),
            )
            await self.github_refresh.start()

    async def stop(self) -> None:
        if self.github_refresh:
            await self.github_refresh.stop()

    async def _refresh_github_cache(self, reason: str, files_changed: list[str]):
        repo = self.worktree_info.path
        try:
            repo_obj = GitManager(config=self.config).get_repo(repo)
            branch_name = repo_obj.head.shorthand
        except Exception:
            return
        await self.get_pr_info(branch_name, force_refresh=True)

    async def get_pr_info(
        self,
        branch_name: str,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        current_time = time.time()
        if (
            not force_refresh
            and self.cached_pr_info is not None
            and self.pr_last_fetched is not None
            and (current_time - self.pr_last_fetched) < 60
        ):
            return self.cached_pr_info
        if not self.github_interface:
            self.cached_pr_info = None
            self.pr_last_fetched = current_time
            return None
        pr_info_data = None
        try:

            def _fetch_pr_info():
                return self.github_interface.pr_search(branch_name)

            loop = asyncio.get_event_loop()
            prs = await loop.run_in_executor(None, _fetch_pr_info)
            if prs:
                pr = prs[0]
                pr_info_data = {
                    "number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "draft": pr.draft,
                    "mergeable": pr.mergeable,
                    "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "html_url": pr.html_url,
                }
        except Exception:
            pr_info_data = None
        self.cached_pr_info = pr_info_data
        self.pr_last_fetched = current_time
        return pr_info_data



    async def _refresh_github_cache(self, reason: str, files_changed: list[str]):
        """Callback for debounced GitHub refresh system."""
        logger.info(f"Refreshing GitHub cache: {reason} (files: {files_changed})")

        # Get current branch
        try:
            repo = self.git_manager.get_repo(self.worktree_info.path)
            branch_name = repo.head.shorthand
        except Exception as e:
            logger.warning(
                f"Could not get current branch for {self.worktree_info.name}: {e}",
            )
            return

        # Force refresh PR info (bypasses cache)
        await self._get_github_pr_info(branch_name, force_refresh=True)

    # Old _parse_response method removed - now using GitStatusdProtocol

    @property
    def is_running(self) -> bool:
        """Check if the gitstatusd process is running."""
        return self.process and self.process.returncode is None


class WtDaemon:
    """Main worktree management daemon that handles all worktree operations."""

    def __init__(self, config):
        from ..shared.configuration import Configuration

        self.config: Configuration = config
        logger.info(
            "Daemon configuration loaded - worktrees_dir: %s, github_repo: %s",
            self.config.worktrees_dir_resolved,
            self.config.github_repo,
        )
        logger.info(
            "GitHub refresh configuration - debounce_delay: %.1fs, periodic_interval: %.1fs",
            self.config.github_debounce_delay.total_seconds(),
            self.config.github_periodic_interval.total_seconds(),
        )
        logger.info(
            "Post-creation script configuration: %s",
            self.config.post_creation_script or "None",
        )

        # Initialize GitHub interface
        self.github_interface = None
        if self.config.github_enabled and self.config.github_repo:
            try:
                from .github_client import GitHubInterface

                self.github_interface = GitHubInterface(self.config.github_repo)
                logger.info(
                    "GitHub interface initialized for repo: %s",
                    self.config.github_repo,
                )
            except Exception as e:
                logger.warning(
                    "Failed to initialize GitHub interface for %s: %s",
                    self.config.github_repo,
                    e,
                )

        # Track daemon health state using proper protocol types
        from ..shared.protocol import DaemonHealth, DaemonHealthStatus

        self.daemon_health = DaemonHealth(
            status=DaemonHealthStatus.OK,
            last_error=None,
            last_error_time=None,
            github_errors=0,
            gitstatusd_errors=0,
        )
        self.daemon_dir = self.config.daemon_dir
        self.socket_path = self.config.daemon_socket_file
        self.pid_file = self.config.daemon_pid_file

        # Managed state
        self.known_worktrees: dict[Path, WorktreeInfo] = {}
        self.gitstatusd_clients: dict[Path, GitstatusdClient] = {}
        self.pr_services: dict[Path, PRService] = {}
        self.git_manager = GitManager(config=self.config)
        self.repo_meta = RepoMetaService(self.git_manager, self.config)
        from .worktree_service import WorktreeService
        self.worktree_service = WorktreeService(self.git_manager, self.github_interface)

        # Server state
        self.server: asyncio.Server | None = None
        self.running = False
        self.discovery_task: asyncio.Task | None = None
        self.discovery_scanning: bool = False

        # Ensure daemon directory exists
        self.daemon_dir.mkdir(exist_ok=True)

    def _record_error(self, error_type: str, error_message: str):
        """Record an error and update daemon health status."""
        from ..shared.protocol import DaemonHealthStatus

        logger.error(f"{error_type}: {error_message}")

        self.daemon_health.last_error = f"{error_type}: {error_message}"
        self.daemon_health.last_error_time = datetime.now()
        self.daemon_health.status = DaemonHealthStatus.ERROR

        if error_type.lower().startswith("github"):
            self.daemon_health.github_errors += 1
        elif error_type.lower().startswith("gitstatusd"):
            self.daemon_health.gitstatusd_errors += 1

    def _record_github_error(self, error_message: str):
        """Record a GitHub-specific error."""
        self._record_error("GitHub", error_message)

    def _record_gitstatusd_error(self, error_message: str):
        """Record a gitstatusd-specific error."""
        self._record_error("GitStatusd", error_message)

    def _clear_errors_if_healthy(self):
        """Clear daemon error state if recent operations are succeeding."""
        from ..shared.protocol import DaemonHealthStatus

        # Only clear if currently in error state
        if self.daemon_health.status == DaemonHealthStatus.ERROR:
            # Check if error is old enough to consider clearing
            if (
                self.daemon_health.last_error_time
                and (
                    datetime.now() - self.daemon_health.last_error_time
                ).total_seconds()
                > 60
            ):
                self.daemon_health.status = DaemonHealthStatus.OK
                self.daemon_health.last_error = None
                self.daemon_health.last_error_time = None
                logger.info("Daemon health status cleared - operations are succeeding")

    def _validate_gitstatusd(self) -> tuple[str, str | None]:
        """Validate gitstatusd binary availability.

        Returns:
            tuple: (gitstatusd_path, error_message) where error_message is None on success
        """
        # Use config value if set
        if self.config.gitstatusd_path:
            gitstatusd_path = str(self.config.gitstatusd_path)
            try:
                result = subprocess.run(
                    [gitstatusd_path, "--version"],
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    logger.info("Using configured gitstatusd at: %s", gitstatusd_path)
                    return gitstatusd_path, None
                return (
                    None,
                    f"Configured gitstatusd path not working: {gitstatusd_path} (exit code {result.returncode})",
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
                return (
                    None,
                    f"Configured gitstatusd path failed: {gitstatusd_path} ({e})",
                )

        # Only check PATH - no hardcoded locations
        gitstatusd_cmd = "gitstatusd"
        if shutil.which(gitstatusd_cmd):
            try:
                result = subprocess.run(
                    [gitstatusd_cmd, "--version"],
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    logger.info("Found gitstatusd on PATH: %s", gitstatusd_cmd)
                    return gitstatusd_cmd, None
                return (
                    None,
                    f"gitstatusd found on PATH but not working (exit code {result.returncode})",
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
                return None, f"gitstatusd found on PATH but failed to execute: {e}"

        return None, (
            "gitstatusd binary not found. Please install gitstatusd and ensure it's available on PATH, "
            "or configure gitstatusd_path in your config file. "
            "Common installation: brew install romkatv/gitstatus/gitstatus"
        )

    def _find_gitstatusd(self) -> str | None:
        """Find gitstatusd binary (legacy method for backward compatibility)."""
        gitstatusd_path, error = self._validate_gitstatusd()
        if error:
            logger.error(error)
        return gitstatusd_path

    def _validate_configuration(self) -> str | None:
        """Validate daemon configuration.

        Returns:
            str: Error message if configuration is invalid, None if valid
        """
        errors = []

        # Check required paths exist
        if not self.config.main_repo_resolved.exists():
            errors.append(
                f"Main repository does not exist: {self.config.main_repo_resolved}",
            )

        if not self.config.main_repo_resolved.is_dir():
            errors.append(
                f"Main repository is not a directory: {self.config.main_repo_resolved}",
            )

        # Check if main repo is actually a git repository
        git_dir = self.config.main_repo_resolved / ".git"
        if not git_dir.exists():
            errors.append(
                f"Main repository is not a git repository (no .git directory): {self.config.main_repo_resolved}",
            )

        # Check worktrees directory can be created
        worktrees_dir = self.config.worktrees_dir_resolved
        if worktrees_dir.exists() and not worktrees_dir.is_dir():
            errors.append(
                f"Worktrees directory path exists but is not a directory: {worktrees_dir}",
            )

        # Check daemon directory permissions
        try:
            self.daemon_dir.mkdir(exist_ok=True)
        except PermissionError:
            errors.append(
                f"Cannot create daemon directory (permission denied): {self.daemon_dir}",
            )
        except Exception as e:
            errors.append(f"Cannot create daemon directory: {self.daemon_dir} ({e})")

        # Validate GitHub configuration if enabled
        if self.config.github_enabled and not self.config.github_repo:
            errors.append("GitHub is enabled but github_repo is not configured")

        if errors:
            return "Configuration validation failed:\n" + "\n".join(
                f"  - {error}" for error in errors
            )

        return None

    async def discover_worktrees(self) -> None:
        """Discover worktrees by scanning the filesystem."""
        worktrees_dir = self.config.worktrees_dir_resolved
        if not worktrees_dir.exists():
            return

        self.discovery_scanning = True
        logger.debug("Scanning for worktrees in %s", worktrees_dir)

        current_worktrees = set()

        # Scan worktree directory
        for path in worktrees_dir.iterdir():
            if path.is_dir():
                # Accept both full clones and linked worktrees
                if (path / ".git").exists() or (path / ".git").is_file():
                    worktree_info = WorktreeInfo(path, path.name)
                    current_worktrees.add(worktree_info)

                # Update existing or add new
                if path in self.known_worktrees:
                    self.known_worktrees[path].last_seen = time.time()
                else:
                    logger.info("Discovered new worktree: %s", path.name)
                    self.known_worktrees[path] = worktree_info
                    asyncio.create_task(
                        self._start_gitstatusd_for_worktree(worktree_info),
                    )

        # Detect disappeared worktrees
        disappeared = set(self.known_worktrees.keys()) - {
            wt.path for wt in current_worktrees
        }

        for disappeared_path in disappeared:
            worktree_info = self.known_worktrees[disappeared_path]
            logger.info("Worktree disappeared: %s", worktree_info.name)
            await self._stop_gitstatusd_for_worktree(worktree_info)
            del self.known_worktrees[disappeared_path]

        self.discovery_scanning = False

    async def _start_gitstatusd_for_worktree(self, worktree_info: WorktreeInfo) -> None:
        """Start gitstatusd for a worktree."""
        gitstatusd_path = self._find_gitstatusd()
        if not gitstatusd_path:
            logger.error(
                "gitstatusd binary not found, cannot start process for %s",
                worktree_info.name,
            )
            return

        if worktree_info.path in self.gitstatusd_clients:
            return  # Already managed

        if worktree_info.path in self.gitstatusd_clients:
            return
        gs_client = GitstatusdClient(
            worktree_info,
            self.config,
            self.git_manager,
            error_callback=self._record_gitstatusd_error,
        )
        await gs_client.start()
        self.gitstatusd_clients[worktree_info.path] = gs_client
        prsvc = PRService(self.github_interface, self.config, worktree_info)
        await prsvc.start()
        self.pr_services[worktree_info.path] = prsvc

        logger.info(
            "Started gitstatusd for worktree %s (GitHub: %s)",
            worktree_info.name,
            "enabled" if self.github_interface else "disabled",
        )

    async def _stop_gitstatusd_for_worktree(self, worktree_info: WorktreeInfo) -> None:
        """Stop gitstatusd for a worktree."""
        gs_client = self.gitstatusd_clients.get(worktree_info.path)
        if gs_client:
            await gs_client.stop()
            del self.gitstatusd_clients[worktree_info.path]
            logger.info("Stopped gitstatusd for worktree %s", worktree_info.name)
        prsvc = self.pr_services.get(worktree_info.path)
        if prsvc:
            await prsvc.stop()
            del self.pr_services[worktree_info.path]

    async def _periodic_discovery(self) -> None:
        """Periodic discovery loop."""
        while self.running:
            try:
                await self.discover_worktrees()
                await asyncio.sleep(30)  # Discover every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic discovery: %s", e, exc_info=True)
                await asyncio.sleep(30)

    async def handle_client_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client request using JSON-RPC 2.0 protocol."""
        start_time = time.time()

        try:
            # Read request line
            data = await reader.readline()
            if not data:
                return

            # Parse JSON-RPC request
            try:
                request = parse_request(data.decode().strip())
                request_id = request.id
                method = request.method
                logger.debug("Handling JSON-RPC request %s: %s", request_id, method)
            except ValueError as e:
                error_response = create_error_response(
                    ErrorCodes.PARSE_ERROR,
                    f"Parse error: {e}",
                    uuid.uuid4(),
                )
                await self._send_response(writer, error_response)
                return

            # Kick discovery opportunistically but do not block request handling
            if not self.known_worktrees and not self.discovery_scanning:
                asyncio.create_task(self.discover_worktrees())

            # Handle different method types
            try:
                if method == "get_status":
                    response = await self._handle_status_request(request, start_time)
                elif method == "ping":
                    response = await self._handle_ping_request(request, start_time)
                elif method == "shutdown":
                    response = await self._handle_shutdown_request(request)
                elif method == "worktree_create":
                    response = await self._handle_worktree_create_request(
                        request,
                        start_time,
                        writer,
                    )
                elif method == "worktree_delete":
                    response = await self._handle_worktree_delete_request(
                        request,
                        start_time,
                    )
                elif method == "worktree_list":
                    response = await self._handle_worktree_list_request(
                        request,
                        start_time,
                    )
                elif method == "worktree_identify":
                    response = await self._handle_worktree_identify_request(
                        request,
                        start_time,
                    )
                elif method == "worktree_get_by_name":
                    response = await self._handle_worktree_get_by_name_request(
                        request,
                        start_time,
                    )
                elif method == "worktree_resolve_path":
                    response = await self._handle_worktree_resolve_path_request(
                        request,
                        start_time,
                    )
                elif method == "worktree_teleport_target":
                    response = await self._handle_worktree_teleport_target_request(
                        request,
                        start_time,
                    )
                else:
                    error_response = create_error_response(
                        ErrorCodes.METHOD_NOT_FOUND,
                        f"Method '{method}' not found",
                        request_id,
                        request_id,
                    )
                    await self._send_response(writer, error_response)
                    return

                # Send successful response
                await self._send_response(writer, response)

            except Exception as e:
                logger.exception("Error handling method %s", method)
                error_response = create_error_response(
                    ErrorCodes.INTERNAL_ERROR,
                    f"Internal error: {e}",
                    request_id,
                )
                try:
                    await self._send_response(writer, error_response)
                except Exception:
                    pass

        except Exception:
            logger.exception("Error handling client request")
        finally:
            writer.close()
            await writer.wait_closed()

    def _create_success_response(self, result: Any, request_id: uuid.UUID) -> Response:
        """Create a successful JSON-RPC response."""
        return Response(result=result, id=request_id)

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        response: Response | ErrorResponse,
    ) -> None:
        """Send a JSON-RPC response to the client."""
        response_data = response.model_dump_json().encode()
        writer.write(response_data)
        writer.write(b"\n")
        await writer.drain()

    async def _handle_status_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle get_status JSON-RPC method."""
        try:
            # Parse parameters
            params = StatusParams.model_validate(request.params)
            worktree_ids = params.worktree_ids

            # Convert WorktreeIDs to paths for internal processing
            if worktree_ids:
                from ..shared.protocol import parse_worktree_id

                worktree_paths = []
                for wtid in worktree_ids:
                    worktree_name = parse_worktree_id(wtid)
                    worktree_path = self.config.worktrees_dir / worktree_name
                    worktree_paths.append(worktree_path)
            else:
                # If no IDs specified, ensure discovery has run at least once
                if not self.known_worktrees:
                    await self.discover_worktrees()
                worktree_paths = list(self.known_worktrees.keys())
                # If discovery found fewer paths than git knows about (newly added), cross-check via git
                git_paths = [wt.path for wt in self.git_manager.list_worktrees() if not wt.is_main]
                if git_paths and len(worktree_paths) < len(git_paths):
                    # Merge any missing git paths into known_worktrees and schedule their startup
                    for p in git_paths:
                        if p not in self.known_worktrees and p.exists():
                            wt_info = WorktreeInfo(p, p.name)
                            self.known_worktrees[p] = wt_info
                            asyncio.create_task(self._start_gitstatusd_for_worktree(wt_info))
                    worktree_paths = list(self.known_worktrees.keys())
                logger.debug(
                    "No specific worktrees requested, returning all %d discovered",
                    len(worktree_paths),
                )

            # Always return unified StatusResponse (whether single or multiple worktrees)
            results = {}
            individual_times = {}

            # Process all worktrees concurrently
            async def process_single_worktree(worktree_path) -> WorktreeGitStatus:
                single_start = time.time()
                gs_client = self.gitstatusd_clients.get(worktree_path)
                worktree_last_error: str | None = None

                if gs_client:
                    try:
                        # Non-blocking: use cache and trigger background refresh
                        dirty_files, untracked_files, last_updated_at, have_cache = (
                            gs_client.get_cached_working_status()
                        )
                        cache_age_ms = (
                            (time.time() - last_updated_at.timestamp()) * 1000
                            if last_updated_at
                            else None
                        )
                        if not have_cache:
                            # Try a small bounded refresh to avoid showing misleading 'clean'
                            try:
                                await asyncio.wait_for(gs_client.update_working_status(), timeout=1.0)
                                dirty_files, untracked_files, last_updated_at, have_cache = (
                                    gs_client.get_cached_working_status()
                                )
                                cache_age_ms = (
                                    (time.time() - last_updated_at.timestamp()) * 1000
                                    if last_updated_at
                                    else None
                                )
                            except asyncio.TimeoutError:
                                asyncio.create_task(gs_client.update_working_status())
                        if last_updated_at is None:
                            last_updated_at = datetime.now()
                            cache_age_ms = None
                        try:
                            commit_info_data, ahead_behind, branch_name = (
                                self.repo_meta.compute_meta(worktree_path)
                            )
                        except Exception as e:
                            commit_info_data = None
                            ahead_behind = (0, 0)
                            branch_name = "HEAD"
                            worktree_last_error = f"meta: {e}"
                        prsvc = self.pr_services.get(worktree_path)
                        pr_info_data = None
                        if prsvc:
                            try:
                                pr_info_data = await asyncio.wait_for(
                                    prsvc.get_pr_info(branch_name),
                                    timeout=0.75,
                                )
                            except asyncio.TimeoutError:
                                pr_info_data = None
                        is_cached = have_cache
                        is_stale = bool(cache_age_ms and cache_age_ms > self.config.cache_refresh_age.total_seconds() * 1000)
                        state = "running" if gs_client.is_running else "stopped"
                    except asyncio.TimeoutError:
                        single_time = (time.time() - single_start) * 1000
                        state = "starting"
                        dirty_files, untracked_files = [], []
                        try:
                            commit_info_data, ahead_behind, branch_name = (
                                self.repo_meta.compute_meta(worktree_path)
                            )
                        except Exception as e:
                            commit_info_data = None
                            ahead_behind = (0, 0)
                            branch_name = "HEAD"
                            worktree_last_error = f"meta: {e}"
                        last_updated_at = datetime.now()
                        pr_info_data = None
                        is_cached = False
                        cache_age_ms = None
                        is_stale = False
                else:
                    single_time = (time.time() - single_start) * 1000
                    state = "stopped"
                    dirty_files, untracked_files = [], []
                    try:
                        commit_info_data, ahead_behind, branch_name = (
                            self.repo_meta.compute_meta(worktree_path)
                        )
                    except Exception as e:
                        commit_info_data = None
                        ahead_behind = (0, 0)
                        branch_name = "HEAD"
                        worktree_last_error = f"meta: {e}"
                    last_updated_at = datetime.now()
                    pr_info_data = None
                    is_cached = False
                    cache_age_ms = None
                    is_stale = False

                commit_info = (CommitInfo.model_validate(commit_info_data) if commit_info_data else None)
                from .worktree_ids import make_worktree_id

                wtid = make_worktree_id(worktree_path.name)
                pr_info = None
                if pr_info_data:
                    from ..shared.github_models import PRInfo, coerce_prdata

                    pr_info = PRInfo(
                        branch=branch_name,
                        pr_data=coerce_prdata(pr_info_data),
                    )
                single_time = (time.time() - single_start) * 1000
                return WorktreeGitStatus(
                    worktree_path_str=str(wtid),
                    status_result=StatusResult(
                        wtid=wtid,
                        name=worktree_path.name,
                        absolute_path=str(worktree_path),
                        branch_name=branch_name,
                        has_dirty_files=len(dirty_files) > 0,
                        has_untracked_files=len(untracked_files) > 0,
                        processing_time_ms=single_time,
                        last_updated_at=last_updated_at,
                        is_cached=is_cached,
                        cache_age_ms=cache_age_ms,
                        is_stale=is_stale,
                        commit_info=commit_info,
                        ahead_count=ahead_behind[0],
                        behind_count=ahead_behind[1],
                        is_main=worktree_path.resolve()
                        == self.config.main_repo_resolved.resolve(),
                        upstream_branch=self.config.upstream_branch,
                        pr_info=pr_info,
                        gitstatusd_state=GitstatusdState.RUNNING
                        if state == "running"
                        else (
                            GitstatusdState.STARTING
                            if state == "starting"
                            else (
                                GitstatusdState.RESTARTING
                                if state == "restarting"
                                else (
                                    GitstatusdState.FAILED
                                    if state == "failed"
                                    else GitstatusdState.STOPPED
                                )
                            )
                        ),
                        restarts=0,
                        last_error=worktree_last_error,
                    ),
                    processing_time_ms=single_time,
                )
                # Fallback: minimal status via GitManager when gitstatusd unavailable
                single_time = (time.time() - single_start) * 1000
                try:
                    (
                        dirty_files,
                        untracked_files,
                    ) = await self.git_manager.get_working_directory_status(
                        worktree_path,
                    )
                    commit_info_data = self.git_manager.get_commit_info(
                        "HEAD",
                        worktree_path,
                    )
                    commit_info = (CommitInfo.model_validate(commit_info_data) if commit_info_data else None)
                    branch_name = (
                        self.git_manager.get_repo(worktree_path).head.shorthand
                        if not self.git_manager.get_repo(worktree_path).head_is_detached
                        else "HEAD"
                    )
                except Exception:
                    dirty_files, untracked_files, commit_info, branch_name = (
                        [],
                        [],
                        None,
                        "HEAD",
                    )
                from .worktree_ids import make_worktree_id

                wtid = make_worktree_id(worktree_path.name)
                return WorktreeGitStatus(
                    worktree_path_str=str(wtid),
                    status_result=StatusResult(
                        wtid=wtid,
                        name=worktree_path.name,
                        absolute_path=str(worktree_path),
                        branch_name=branch_name,
                        has_dirty_files=len(dirty_files) > 0,
                        has_untracked_files=len(untracked_files) > 0,
                        processing_time_ms=single_time,
                        last_updated_at=datetime.now(),
                        is_cached=False,
                        cache_age_ms=None,
                        is_stale=False,
                        commit_info=commit_info,
                        ahead_count=0,
                        behind_count=0,
                        is_main=worktree_path.resolve()
                        == self.config.main_repo_resolved.resolve(),
                        upstream_branch=self.config.upstream_branch,
                        pr_info=None,
                        gitstatusd_state=GitstatusdState.STOPPED,
                        restarts=0,
                        last_error=worktree_last_error,
                    ),
                    processing_time_ms=single_time,
                )

            # Run all worktree processing concurrently
            worktree_results = await asyncio.gather(
                *[
                    process_single_worktree(worktree_path)
                    for worktree_path in worktree_paths
                ],
            )

            # Collect results from concurrent processing
            for result in worktree_results:
                if result.status_result:
                    results[result.worktree_path_str] = result.status_result
                    individual_times[result.worktree_path_str] = (
                        result.processing_time_ms
                    )

            total_time = (time.time() - start_time) * 1000
            # Compute readiness summary
            from ..shared.protocol import ComponentState, ReadinessSummary

            total_wt = len(self.known_worktrees)
            with_git = sum(1 for p in self.gitstatusd_clients.values() if p.is_running)
            any_wt_error = any(r.last_error for r in results.values())
            github_state = ComponentState.DISABLED
            if self.github_interface:
                github_state = ComponentState.OK
                # If any PRService hasn't fetched yet, reflect warming-up state
                for prsvc in self.pr_services.values():
                    if prsvc.cached_pr_info is None:
                        github_state = ComponentState.STARTING
                        break
            readiness = ReadinessSummary(
                total_worktrees=total_wt,
                with_gitstatusd=with_git,
                discovery_scanning=self.discovery_scanning,
                github=github_state,
            )

            from ..shared.protocol import (
                ComponentsStatus,
                ComponentState,
                ComponentStatus,
            )

            components = ComponentsStatus(
                discovery=ComponentStatus(
                    state=ComponentState.SCANNING
                    if self.discovery_scanning
                    else ComponentState.OK,
                ),
                github=ComponentStatus(
                    state=github_state,
                ),
                gitstatusd=ComponentStatus(
                    state=ComponentState.OK
                    if (with_git == total_wt and total_wt > 0 and not any_wt_error)
                    else ComponentState.ERROR,
                    metrics={"running": with_git, "total": total_wt},
                ),
            )

            status_response = StatusResponse(
                results={k: v for k, v in results.items()},
                total_processing_time_ms=total_time,
                individual_processing_times_ms=individual_times,
                concurrent_requests=len(worktree_paths),
                daemon_health=self.daemon_health,
                readiness_summary=readiness,
                components=components,
            )

            # Clear error status if operations are succeeding
            self._clear_errors_if_healthy()

            return self._create_success_response(status_response, request.id)

        except Exception as e:
            logger.error("Error in status request: %s", e)
            raise

    async def _handle_ping_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle ping JSON-RPC method."""
        result = PingResult(
            daemon_pid=os.getpid(),
            started_at=datetime.fromtimestamp(start_time),
            discovered_worktrees=list(self.known_worktrees.keys()),
        )
        return self._create_success_response(result, request.id)

    async def _handle_shutdown_request(self, request: Request) -> Response:
        """Handle shutdown JSON-RPC method."""
        logger.info("Received shutdown request")
        asyncio.create_task(self.stop())
        return self._create_success_response("shutting down", request.id)

    async def _handle_worktree_create_request(
        self,
        request: Request,
        start_time: float,
        writer: asyncio.StreamWriter | None = None,
    ) -> Response:
        """Handle worktree_create JSON-RPC method."""
        try:
            # Parse parameters
            params = WorktreeCreateParams.model_validate(request.params)

            # Validate worktree name (no slashes)
            if "/" in params.name:
                raise ValueError(
                    f"Worktree name '{params.name}' cannot contain slashes",
                )

            # Derive paths and branch name from simple name
            worktree_path = self.config.worktrees_dir / params.name
            branch_name = f"{self.config.branch_prefix}{params.name}"
            worktree_id = make_worktree_id(params.name)

            # Check if worktree already exists
            if worktree_path.exists():
                raise ValueError(f"Worktree path {worktree_path} already exists")

            # If a post-creation script is configured, validate it exists before any side effects
            if self.config.post_creation_script:
                script = self.config.post_creation_script
                if not script.exists() or not script.is_file():
                    raise ValueError(
                        f"Post-creation script configured but not found or not a file: {script}",
                    )

            # Create worktree via service (handles hydration). Defer script execution here for streaming.
            svc = self.worktree_service
            # Resolve source branch from source_wtid if provided
            source_path = None
            if params.source_wtid:
                from .worktree_ids import wtid_to_path
                source_path = wtid_to_path(self.config, params.source_wtid)
                if not source_path.exists():
                    raise ValueError(f"Source worktree path not found: {source_path}")
                # Derive branch from source repo HEAD
                src_repo = self.git_manager.get_repo(source_path)
                src_branch = src_repo.head.shorthand
            else:
                src_branch = self.config.upstream_branch

            svc.create_worktree(
                self.config,
                params.name,
                source_worktree=source_path,
                source_branch=src_branch,
            )

            post = None
            if self.config.post_creation_script:
                try:
                    script = self.config.post_creation_script
                    if not script.exists() or not script.is_file():
                        raise FileNotFoundError(
                            f"Post-creation script not found at execution time: {script}",
                        )
                    from .worktree_service import WorktreeService
                    post = await WorktreeService.run_post_creation_script(
                        str(script),
                        worktree_path,
                        writer,
                    )
                except Exception as e:
                    post = {
                        "ran": True,
                        "exit_code": None,
                        "stdout": None,
                        "stderr": None,
                        "error": str(e),
                    }
                    logger.warning(
                        f"Post-creation script error for {worktree_path}: {e}",
                    )

            from ..shared.protocol import HookRunResult

            result = WorktreeCreateResult(
                wtid=worktree_id,
                name=params.name,
                absolute_path=str(worktree_path),
                branch_name=branch_name,
                success=True,
                post_hook=(HookRunResult(**post) if post else None),
            )

            logger.info(
                "Created worktree %s at %s (branch: %s)",
                params.name,
                worktree_path,
                branch_name,
            )
            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error creating worktree: %s", e)
            raise


    async def _handle_worktree_delete_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle worktree_delete JSON-RPC method."""
        try:
            # Parse parameters
            params = WorktreeDeleteParams.model_validate(request.params)

            # Parse WorktreeID to get directory name
            from ..shared.protocol import parse_worktree_id

            worktree_name = parse_worktree_id(params.wtid)
            worktree_path = self.config.worktrees_dir / worktree_name

            # Validate worktree exists
            if not worktree_path.exists():
                raise ValueError(
                    f"Worktree {worktree_name} does not exist at {worktree_path}",
                )

            # Remove worktree
            self.git_manager.worktree_remove(str(worktree_path), force=True)
            try:
                import shutil

                if worktree_path.exists():
                    shutil.rmtree(worktree_path)
            except Exception as e:
                logger.warning("Filesystem cleanup failed for %s: %s", worktree_path, e)

            result = WorktreeDeleteResult(
                wtid=params.wtid,
                success=True,
                message=f"Deleted worktree {worktree_name}",
            )

            logger.info("Deleted worktree %s at %s", worktree_name, worktree_path)
            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error deleting worktree: %s", e)
            raise

    async def _handle_worktree_list_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle worktree_list JSON-RPC method."""
        try:
            # Get all worktrees from git
            worktree_infos = self.git_manager.list_worktrees()

            # Convert to protocol format, filtering out main repo
            worktrees = []
            for info in worktree_infos:
                if not info.is_main:
                    # Extract worktree name from path
                    worktree_name = info.path.name
                    worktree_id = make_worktree_id(worktree_name)

                    from ..shared.protocol import WorktreeInfo as ProtocolWorktreeInfo

                    worktrees.append(
                        ProtocolWorktreeInfo(
                            wtid=worktree_id,
                            name=worktree_name,
                            absolute_path=str(info.path),
                            branch_name=info.branch,
                            exists=info.exists,
                            is_main=False,
                        ),
                    )

            result = WorktreeListResult(worktrees=worktrees)
            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error listing worktrees: %s", e)
            raise

    async def _handle_worktree_identify_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle worktree_identify JSON-RPC method."""
        try:
            # Parse parameters
            params = WorktreeIdentifyParams.model_validate(request.params)
            absolute_path = Path(params.absolute_path)

            # Check if path is within worktrees directory
            try:
                rel_path = absolute_path.relative_to(self.config.worktrees_dir)
                worktree_name = rel_path.parts[0] if rel_path.parts else None
                # Calculate relative path within the worktree (everything after worktree_name)
                if len(rel_path.parts) > 1:
                    relative_path = str(Path(*rel_path.parts[1:]))
                else:
                    relative_path = ""
            except ValueError:
                # Path is not within worktrees directory - check if it's main repo
                try:
                    absolute_path.relative_to(self.config.main_repo)
                    # Path is within main repo
                    worktree_name = MAIN_WORKTREE_DISPLAY_NAME
                    relative_path = str(
                        absolute_path.relative_to(self.config.main_repo),
                    )
                except ValueError:
                    # Path is not within any managed worktree
                    worktree_name = None
                    relative_path = None

            if worktree_name and absolute_path.exists():
                # Verify this is actually a managed worktree using the centralized resolver
                worktree_infos = self.git_manager.list_worktrees()
                found_worktree = resolve_worktree_name_to_info(
                    worktree_name,
                    worktree_infos,
                )

                if not found_worktree:
                    # Path appeared to be in worktrees dir but isn't actually managed
                    raise ValueError(f"Path {absolute_path} is not a managed worktree")

                # Generate appropriate WorktreeID
                if found_worktree.is_main:
                    worktree_id = make_worktree_id(MAIN_WORKTREE_DISPLAY_NAME)
                    resolved_name = MAIN_WORKTREE_DISPLAY_NAME
                else:
                    worktree_id = make_worktree_id(found_worktree.path.name)
                    resolved_name = found_worktree.path.name

                result = WorktreeIdentifyResult(
                    wtid=worktree_id,
                    name=resolved_name,
                    is_worktree=True,
                    relative_path=relative_path,
                )
            else:
                # Path not recognized as managed worktree
                raise ValueError(f"Path {absolute_path} is not a managed worktree")

            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error identifying worktree: %s", e)
            raise

    async def _handle_worktree_get_by_name_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle worktree_get_by_name JSON-RPC method."""
        try:
            # Parse parameters
            params = WorktreeGetByNameParams.model_validate(request.params)
            name = params.name

            # Check if worktree exists by looking at git worktrees
            worktree_infos = self.git_manager.list_worktrees()
            found_worktree = resolve_worktree_name_to_info(name, worktree_infos)

            if found_worktree:
                # Worktree exists
                if found_worktree.is_main:
                    wtid = make_worktree_id(MAIN_WORKTREE_DISPLAY_NAME)
                    worktree_name = MAIN_WORKTREE_DISPLAY_NAME
                else:
                    wtid = make_worktree_id(found_worktree.path.name)
                    worktree_name = found_worktree.path.name

                result = WorktreeGetByNameResult(
                    wtid=wtid,
                    name=worktree_name,
                    exists=True,
                    absolute_path=str(found_worktree.path),
                )
            else:
                # Worktree does not exist
                result = WorktreeGetByNameResult(
                    wtid=None,
                    name=None,
                    exists=False,
                    absolute_path=None,
                )

            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error getting worktree by name: %s", e)
            raise

    def _find_current_worktree_info(
        self,
        current_path: Path,
        worktree_infos: list,
    ) -> tuple[object | None, str | None]:
        """Find current worktree and relative path from current working directory."""
        # Check main repo first
        if current_path.is_relative_to(self.config.main_repo_resolved):
            for info in worktree_infos:
                if info.is_main:
                    relative_path = str(
                        current_path.relative_to(self.config.main_repo_resolved),
                    )
                    return info, relative_path

        # Check worktrees directory
        for info in worktree_infos:
            if not info.is_main and current_path.is_relative_to(info.path):
                relative_path = str(current_path.relative_to(info.path))
                return info, relative_path

        return None, None

    def _find_target_worktree(
        self,
        worktree_name: str | None,
        current_path: Path,
        worktree_infos: list,
    ) -> tuple[object, str | None]:
        """Find target worktree and current relative path for path resolution."""
        if worktree_name:
            # Path in specified worktree - get worktree by name
            found_worktree = resolve_worktree_name_to_info(
                worktree_name,
                worktree_infos,
            )
            if not found_worktree:
                raise ValueError(f"Worktree '{worktree_name}' not found")
            return found_worktree, None

        # Path in current worktree - identify from current_path
        found_worktree, relative_path = self._find_current_worktree_info(
            current_path,
            worktree_infos,
        )
        if not found_worktree:
            raise ValueError(
                f"Current path {current_path} is not in a managed worktree",
            )

        return found_worktree, relative_path

    def _resolve_path_spec(
        self,
        path_spec: str,
        target_path: Path,
        current_relative_path: str | None,
        is_current_worktree: bool,
    ) -> Path:
        """Resolve path specification within a worktree."""
        if path_spec.startswith("/"):
            # Absolute path within worktree
            return target_path / path_spec.lstrip("/")

        if path_spec.startswith("./"):
            # Relative path from current location within worktree
            if not is_current_worktree:
                raise ValueError("Cannot use relative path for different worktree")

            if current_relative_path:
                current_dir = target_path / current_relative_path
            else:
                current_dir = target_path

            return (current_dir / path_spec).resolve()

        # Treat as absolute path within worktree
        return target_path / path_spec

    def _compute_teleport_target(
        self,
        target_repo: Path,
        relative_path: str | None,
    ) -> str:
        """Compute final cd target with path preservation logic."""
        if not relative_path or relative_path == ".":
            return str(target_repo)

        target_subpath = target_repo / relative_path
        if target_subpath.exists() and target_subpath.is_dir():
            return str(target_subpath)

        return str(target_repo)

    async def _handle_worktree_resolve_path_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        """Handle worktree_resolve_path JSON-RPC method."""
        try:
            # Parse parameters
            params = WorktreeResolvePathParams.model_validate(request.params)
            current_path = Path(params.current_path)

            # Get worktree infos once
            worktree_infos = self.git_manager.list_worktrees()

            # Find target worktree and current relative path
            target_worktree, current_relative_path = self._find_target_worktree(
                params.worktree_name,
                current_path,
                worktree_infos,
            )

            # Resolve the path specification
            is_current_worktree = params.worktree_name is None
            resolved_path = self._resolve_path_spec(
                params.path_spec,
                target_worktree.path,
                current_relative_path,
                is_current_worktree,
            )

            result = WorktreeResolvePathResult(absolute_path=str(resolved_path))
            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error resolving worktree path: %s", e)
            raise

    async def _handle_worktree_teleport_target_request(
        self,
        request: Request,
        start_time: float,
    ) -> Response:
        try:
            params = WorktreeTeleportTargetParams.model_validate(request.params)
            current_path = Path(params.current_path)

            # Get worktree infos once
            worktree_infos = self.git_manager.list_worktrees()

            # Get target worktree (early bailout on missing)
            target_worktree = resolve_worktree_name_to_info(
                params.target_name,
                worktree_infos,
            )
            if not target_worktree:
                result = TeleportDoesNotExist(type="does_not_exist", name=params.target_name)
                return self._create_success_response(result, request.id)

            # Find current worktree info
            current_worktree, relative_path = self._find_current_worktree_info(
                current_path,
                worktree_infos,
            )

            # Compute target path
            cd_path = self._compute_teleport_target(target_worktree.path, relative_path)

            result = TeleportCdThere(type="cd_there", cd_path=cd_path)
            return self._create_success_response(result, request.id)

        except Exception as e:
            logger.error("Error computing teleport target: %s", e)
            raise

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting wt daemon for %s", self.config.main_repo_resolved)

        # Emit initial progress handshake to ensure the client always sees at least one line
        write_startup_handshake(
            success=True,
            protocol_version=1,
            ready=False,
            phase="starting",
            redirect_after=False,
        )

        startup_errors = []

        # Validate configuration first
        config_error = self._validate_configuration()
        if config_error:
            startup_errors.append(config_error)

        # Validate post-creation script existence if configured (hard fail at startup)
        if self.config.post_creation_script:
            script = self.config.post_creation_script
            if not script.exists() or not script.is_file():
                startup_errors.append(
                    f"Post-creation script configured but not found or not a file: {script}",
                )

        # Validate gitstatusd availability
        gitstatusd_path, gitstatusd_error = self._validate_gitstatusd()
        if gitstatusd_error:
            startup_errors.append(gitstatusd_error)

        # If there are critical errors, write error handshake and return
        if startup_errors:
            error_message = "\n\n".join(startup_errors)
            write_startup_handshake(
                success=False,
                error_message=error_message,
                protocol_version=1,
            )
            logger.error("Daemon startup failed due to validation errors")
            return

        # Bind socket immediately after validation
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.server = await asyncio.start_unix_server(
            self.handle_client_request,
            self.socket_path,
        )
        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))
        self.running = True

        # Signal listening via single handshake; redirect stdout to log afterward
        write_startup_handshake(
            success=True,
            protocol_version=1,
            ready=True,
            gitstatusd_path=gitstatusd_path,
            discovered_worktrees=[],
            socket_path=str(self.socket_path),
            redirect_after=True,
        )

        # Kick off initial discovery asynchronously
        asyncio.create_task(self.discover_worktrees())

        logger.info("wt daemon started, listening on %s", self.socket_path)

        # Start periodic discovery in the background
        self.discovery_task = asyncio.create_task(self._periodic_discovery())

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping wt daemon")

        self.running = False

        # Cancel discovery task
        if self.discovery_task:
            self.discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.discovery_task

        # Stop all gitstatusd processes
        for process in list(self.gitstatusd_clients.values()):
            await process.stop()

        self.gitstatusd_clients.clear()

        # Stop server
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up files
        if self.socket_path.exists():
            self.socket_path.unlink()
        if self.pid_file.exists():
            self.pid_file.unlink()

        logger.info("wt daemon stopped")


async def run_daemon(config) -> None:
    """Run the daemon with proper signal handling."""
    daemon = WtDaemon(config)

    # Signal handling
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(daemon.stop())

    signal.signal(signal.SIGTERM, lambda s, f: signal_handler())
    signal.signal(signal.SIGINT, lambda s, f: signal_handler())

    try:
        await daemon.start()

        # Wait for server
        if daemon.server:
            async with daemon.server:
                await daemon.server.serve_forever()

    except asyncio.CancelledError:
        pass
    finally:
        await daemon.stop()


if __name__ == "__main__":
    import os
    import sys

    # Load config using the standard discovery system
    from wt.shared.configuration import load_config

    try:
        config = load_config()
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Configure logging to write only to daemon log file
    daemon_dir = config.daemon_dir
    daemon_dir.mkdir(exist_ok=True)
    log_file = daemon_dir / "daemon.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="a"),
            # No StreamHandler - daemon should not output to console
        ],
    )

    # Also capture urllib3 and other third-party debug logs
    # This ensures ALL logging goes to the file, not the console
    urllib3_logger = logging.getLogger("urllib3")
    urllib3_logger.setLevel(logging.DEBUG)
    urllib3_logger.propagate = True  # Ensure it propagates to our file handler

    asyncio.run(run_daemon(config))
