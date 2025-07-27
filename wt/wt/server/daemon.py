"""GitStatusd multiplexing daemon with auto-discovery.

One daemon per main git repository that:
- Auto-discovers worktrees by filesystem scanning
- Manages gitstatusd processes per worktree
- Provides socket-based API for CLI clients
- Handles concurrent requests efficiently
"""

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..shared.protocol import (
    SUPPORTED_METHODS,
    CommitInfo,
    ErrorCodes,
    ErrorResponse,
    PingResult,
    Request,
    Response,
    StatusParams,
    StatusResponse,
    StatusResult,
    create_error_response,
    parse_request,
)
from .git_manager import GitRepositoryManager
from .gitstatusd_protocol import (
    GitStatusdParseError,
    GitStatusdProtocol,
    GitStatusdRequest,
    GitStatusdValidationError,
    gitstatusd_response_to_legacy_format,
)

logger = logging.getLogger(__name__)


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
        self.refresh_callback = refresh_callback  # async function to call when refresh needed

        # Configurable timing
        self.debounce_delay = debounce_delay  # seconds to wait after last change
        self.periodic_interval = periodic_interval  # seconds between periodic refreshes

        # State tracking
        self.pending_refresh_task: Optional[asyncio.Task] = None
        self.last_refresh_time = 0.0
        self.pending_files: Set[str] = set()

        # File watcher
        self.observer: Optional[Observer] = None
        self.event_handler = GitFileHandler(self)

        # Background tasks
        self.periodic_task: Optional[asyncio.Task] = None
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

    def trigger_refresh(self, reason: str, file_path: Optional[str] = None):
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
            self._debounced_refresh(reason, current_time)
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
                    if time_since_last >= self.periodic_interval * 0.8:  # 80% of interval
                        await self._do_refresh("periodic")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic refresh: {e}")
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
            logger.info(f"GitHub refresh completed in {refresh_time:.1f}ms ({fetch_status})")

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
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)

                if process.returncode == 0:
                    logger.debug("Successfully fetched origin/master")
                    return True
                else:
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
                logger.debug(f"Git file change detected: {path_str} (pattern: {pattern})")
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


class GitStatusdProcess:
    """Managed gitstatusd process for a worktree with caching and filesystem watching."""

    def __init__(
        self,
        worktree_info: WorktreeInfo,
        gitstatusd_path: str,
        config,
        git_repo_manager: GitRepositoryManager,
        github_interface=None,
        error_callback=None,
    ):
        from ..shared.config import Config

        self.worktree_info = worktree_info
        self.gitstatusd_path = gitstatusd_path
        self.config: Config = config
        self.git_repo_manager = git_repo_manager
        self.github_interface = github_interface
        self.error_callback = error_callback
        self.process: Optional[asyncio.subprocess.Process] = None
        self.created_at = time.time()
        self.last_used = time.time()
        self.request_count = 0

        # Comprehensive caching with staleness tracking
        self.cached_working_status: Optional[Tuple[List[str], List[str]]] = None
        self.cached_commit_info: Optional[Dict[str, Any]] = None
        self.cached_ahead_behind: Optional[Tuple[int, int]] = None
        self.cached_branch: Optional[str] = None
        self.cached_pr_info: Optional[Dict[str, Any]] = None
        self.last_updated_at: Optional[datetime] = None
        self.cache_lock = threading.Lock()

        # Old filesystem watching variables removed - now handled by DebouncedGitHubRefresh

        # GitHub PR cache with 1-minute TTL + push event refresh
        self.pr_cache_ttl = 60  # 1 minute
        self.pr_last_fetched: Optional[float] = None

        # Debounced GitHub refresh system
        self.github_refresh: Optional[DebouncedGitHubRefresh] = None
        if self.github_interface:
            self.github_refresh = DebouncedGitHubRefresh(
                worktree_info.path,
                self._refresh_github_cache,
                debounce_delay=self.config.github_debounce_delay,
                periodic_interval=self.config.github_periodic_interval,
            )

    async def start(self) -> None:
        """Start the gitstatusd process."""
        if self.process and self.process.returncode is None:
            return  # Already running

        logger.info("Starting gitstatusd for worktree %s", self.worktree_info.name)

        self.process = await asyncio.create_subprocess_exec(
            self.gitstatusd_path,
            "--num-threads=8",
            "--max-num-staged=-1",  # Count all files
            "--max-num-unstaged=-1",  # Count all files
            "--max-num-untracked=-1",  # Count all files
            "--max-commit-summary-length=0",  # Don't need commit summaries
            "--repo-ttl-seconds=3600",  # Keep repo cached for 1 hour
            "--log-level=FATAL",  # Minimal logging
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        logger.debug(
            "gitstatusd started with PID %d for %s", self.process.pid, self.worktree_info.name
        )

        # Old filesystem watching replaced by debounced GitHub refresh system

        # Start GitHub refresh system
        if self.github_refresh:
            await self.github_refresh.start()

        # Perform initial status query to populate cache
        await self._update_cache_from_gitstatusd()

    async def stop(self) -> None:
        """Stop the gitstatusd process."""
        # Stop GitHub refresh system
        if self.github_refresh:
            await self.github_refresh.stop()

        # Old filesystem watching cleanup removed - now handled by DebouncedGitHubRefresh

        if not self.process:
            return

        logger.info("Stopping gitstatusd for worktree %s", self.worktree_info.name)

        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("gitstatusd didn't terminate gracefully, killing it")
            self.process.kill()
            await self.process.wait()

        self.process = None
        logger.debug("gitstatusd stopped for %s", self.worktree_info.name)

    async def get_comprehensive_status(
        self,
    ) -> Tuple[
        List[str],
        List[str],
        Dict[str, Any],
        Tuple[int, int],
        str,
        Optional[Dict[str, Any]],
        datetime,
        bool,
    ]:
        """Get comprehensive status including working directory, commit info, ahead/behind counts, and PR info."""
        self.last_used = time.time()
        self.request_count += 1

        with self.cache_lock:
            # Return cached result if all components are available and fresh
            if (
                self.cached_working_status
                and self.cached_commit_info
                and self.cached_ahead_behind is not None
                and self.cached_branch
                and self.last_updated_at
            ):
                logger.debug(
                    "Returning cached comprehensive status for %s (updated at %s)",
                    self.worktree_info.name,
                    self.last_updated_at,
                )
                dirty_files, untracked_files = self.cached_working_status
                return (
                    dirty_files,
                    untracked_files,
                    self.cached_commit_info,
                    self.cached_ahead_behind,
                    self.cached_branch,
                    self.cached_pr_info,
                    self.last_updated_at,
                    True,
                )

        # No cache available - force fresh query
        logger.debug(
            "No comprehensive cache available for %s, querying all sources", self.worktree_info.name
        )
        return await self._update_comprehensive_cache()

    async def get_status(self) -> Tuple[List[str], List[str], datetime, bool]:
        """Get working directory status only, using cache if available."""
        comprehensive = await self.get_comprehensive_status()
        return comprehensive[0], comprehensive[1], comprehensive[5], comprehensive[6]

    async def _update_cache_from_gitstatusd(self) -> Tuple[List[str], List[str], datetime, bool]:
        """Query gitstatusd and update cache."""
        if not self.process or self.process.returncode is not None:
            await self.start()

        # Send request to gitstatusd using proper protocol
        request_id = str(uuid.uuid4())[:8]
        gitstatusd_request = GitStatusdRequest(
            request_id=request_id,
            directory_path=str(self.worktree_info.path),
            disable_index_computation=False,
        )
        request_data = gitstatusd_request.to_wire_format()

        logger.debug("Sending gitstatusd request %s for %s", request_id, self.worktree_info.name)

        # Check if process is healthy before sending request
        if self.process.returncode is not None:
            logger.warning(
                "gitstatusd process died (returncode=%s) for %s, restarting",
                self.process.returncode,
                self.worktree_info.name,
            )
            await self.start()  # Restart the process

        self.process.stdin.write(request_data.encode())
        await self.process.stdin.drain()

        # Read and parse response using proper protocol
        response = await self.process.stdout.readuntil(b"\x1e")
        response_str = response.decode("utf-8")
        logger.debug(
            "Raw gitstatusd response for %s: %s", self.worktree_info.name, repr(response_str[:200])
        )

        try:
            parsed_response = GitStatusdProtocol.parse_response(response_str)
            dirty_files, untracked_files = gitstatusd_response_to_legacy_format(parsed_response)

            # Log parsed information for debugging
            if parsed_response.is_git_repository:
                logger.debug(
                    "Parsed gitstatusd for %s: %d staged, %d unstaged, %d untracked, branch=%s",
                    self.worktree_info.name,
                    parsed_response.staged_changes or 0,
                    parsed_response.unstaged_changes or 0,
                    parsed_response.untracked_files or 0,
                    parsed_response.local_branch or "detached",
                )
            else:
                logger.warning("Directory %s is not a git repository", self.worktree_info.path)

        except (GitStatusdParseError, GitStatusdValidationError) as e:
            error_msg = f"Failed to parse gitstatusd response for {self.worktree_info.name}: {e}"
            logger.error(error_msg)
            dirty_files, untracked_files = [], []

            # Record the error in daemon health tracking
            if self.error_callback:
                self.error_callback("GitStatusd", error_msg)

        # Update cache
        now = datetime.now()
        with self.cache_lock:
            self.cached_result = (dirty_files, untracked_files)
            self.cached_working_status = (dirty_files, untracked_files)
            self.last_updated_at = now

        logger.debug(
            "Updated cache for %s: %d dirty, %d untracked",
            self.worktree_info.name,
            len(dirty_files),
            len(untracked_files),
        )

        return dirty_files, untracked_files, now, False

    async def _update_comprehensive_cache(
        self,
    ) -> Tuple[
        List[str],
        List[str],
        Dict[str, Any],
        Tuple[int, int],
        str,
        Optional[Dict[str, Any]],
        datetime,
        bool,
    ]:
        """Query all sources and update comprehensive cache."""
        if not self.process or self.process.returncode is not None:
            await self.start()

        # Get working directory status
        dirty_files, untracked_files, _, _ = await self._update_cache_from_gitstatusd()

        # Get git info using git_repo_manager
        try:
            # Get current branch
            repo = self.git_repo_manager.get_repo(self.worktree_info.path)
            branch_name = repo.head.shorthand

            # Get commit info for HEAD
            commit_info_data = self.git_repo_manager.get_commit_info(
                self.worktree_info.path, "HEAD"
            )

            # Get ahead/behind counts relative to default branch
            default_branch = self.git_repo_manager.get_default_branch(
                self.config.main_repo_resolved
            )
            ahead_behind = (0, 0)  # Default for main repo
            if self.worktree_info.path != self.config.main_repo_resolved:
                try:
                    main_repo = self.git_repo_manager.get_repo(self.config.main_repo_resolved)
                    ahead, behind = main_repo.ahead_behind(
                        f"refs/heads/{branch_name}", f"refs/heads/{default_branch}"
                    )
                    ahead_behind = (ahead, behind)
                except Exception as e:
                    error_msg = f"Failed to get ahead/behind for {self.worktree_info.name}: {e}"
                    logger.error(error_msg)

                    # Record the error in daemon health tracking
                    if self.error_callback:
                        self.error_callback("GitStatusd", error_msg)

            # Get GitHub PR info - check cache staleness
            pr_info_data = await self._get_github_pr_info(branch_name)

            # Update comprehensive cache
            now = datetime.now()
            with self.cache_lock:
                self.cached_working_status = (dirty_files, untracked_files)
                self.cached_commit_info = commit_info_data
                self.cached_ahead_behind = ahead_behind
                self.cached_branch = branch_name
                self.cached_pr_info = pr_info_data
                self.last_updated_at = now

            logger.debug(
                "Updated comprehensive cache for %s: %s branch, %d ahead, %d behind",
                self.worktree_info.name,
                branch_name,
                ahead_behind[0],
                ahead_behind[1],
            )

            return (
                dirty_files,
                untracked_files,
                commit_info_data,
                ahead_behind,
                branch_name,
                pr_info_data,
                now,
                False,
            )

        except Exception as e:
            logger.error(
                "Failed to get comprehensive status for %s: %s", self.worktree_info.name, e
            )
            # Record the error in daemon health tracking
            if self.error_callback:
                self.error_callback(
                    "GitStatusd",
                    f"Failed to get comprehensive status for {self.worktree_info.name}: {e}",
                )
            raise  # Don't mask the error - let it propagate

    async def _get_github_pr_info(
        self, branch_name: str, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get GitHub PR info with smart caching - refresh on git operations or every 1 minute."""
        current_time = time.time()

        # Check if we have cached PR info that's still fresh (unless forcing refresh)
        if not force_refresh:
            with self.cache_lock:
                if (
                    self.cached_pr_info is not None
                    and self.pr_last_fetched is not None
                    and (current_time - self.pr_last_fetched) < self.pr_cache_ttl
                ):
                    cache_age = current_time - self.pr_last_fetched
                    logger.info(
                        "GitHub PR cache HIT for branch '%s' (age: %.1fs, worktree: %s)",
                        branch_name,
                        cache_age,
                        self.worktree_info.name,
                    )
                    return self.cached_pr_info

        # Cache miss - need to fetch from GitHub
        cache_age = (current_time - self.pr_last_fetched) if self.pr_last_fetched else "never"
        logger.info(
            "GitHub PR cache MISS for branch '%s' (age: %s, worktree: %s) - fetching from API",
            branch_name,
            cache_age,
            self.worktree_info.name,
        )

        # Skip GitHub API if no interface provided
        if not self.github_interface:
            logger.warning(
                "GitHub interface not available for branch '%s' (worktree: %s)",
                branch_name,
                self.worktree_info.name,
            )
            with self.cache_lock:
                self.cached_pr_info = None
                self.pr_last_fetched = current_time
            return None

        # Make actual GitHub API call
        pr_info_data = None
        try:
            logger.info(
                "GitHub PR API request: searching for PRs with head branch '%s' (worktree: %s)",
                branch_name,
                self.worktree_info.name,
            )
            logger.info("GitHub PR API call: pr_search('%s')", branch_name)

            # Run the GitHub API call in thread pool since it's synchronous
            def _fetch_pr_info():
                return self.github_interface.pr_search(branch_name)

            loop = asyncio.get_event_loop()
            prs = await loop.run_in_executor(None, _fetch_pr_info)

            if prs:
                pr = prs[0]  # Take first PR found
                # Extract the data we need from the PyGithub PR object for serialization
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
                logger.info(
                    "GitHub PR API response: Found PR #%d (%s) for branch '%s' - title: %s",
                    pr.number,
                    pr.state,
                    branch_name,
                    pr.title[:50],
                )
            else:
                logger.info(
                    "GitHub PR API response: No PR found for branch '%s' (worktree: %s)",
                    branch_name,
                    self.worktree_info.name,
                )

        except Exception as e:
            error_msg = f"GitHub PR API request failed for branch '{branch_name}' (worktree: {self.worktree_info.name}): {e}"
            logger.error(error_msg)
            logger.info("GitHub PR API error details: %s", str(e))

            # Record the error in daemon health tracking
            if self.error_callback:
                self.error_callback("GitHub", error_msg)

        # Update cache with result (even if None/error)
        with self.cache_lock:
            self.cached_pr_info = pr_info_data
            self.pr_last_fetched = current_time

        if pr_info_data:
            logger.info(
                "GitHub PR cache updated for branch '%s' (worktree: %s) - PR #%d found",
                branch_name,
                self.worktree_info.name,
                pr_info_data["number"],
            )
        else:
            logger.info(
                "GitHub PR cache updated for branch '%s' (worktree: %s) - no PR found",
                branch_name,
                self.worktree_info.name,
            )

        return pr_info_data

    async def _refresh_github_cache(self, reason: str, files_changed: list[str]):
        """Callback for debounced GitHub refresh system."""
        logger.info(f"Refreshing GitHub cache: {reason} (files: {files_changed})")

        # Get current branch
        try:
            repo = self.git_repo_manager.get_repo(self.worktree_info.path)
            branch_name = repo.head.shorthand
        except Exception as e:
            logger.warning(f"Could not get current branch for {self.worktree_info.name}: {e}")
            return

        # Force refresh PR info (bypasses cache)
        await self._get_github_pr_info(branch_name, force_refresh=True)

    # Old _parse_response method removed - now using GitStatusdProtocol

    @property
    def is_running(self) -> bool:
        """Check if the gitstatusd process is running."""
        return self.process and self.process.returncode is None


class GitStatusdDaemon:
    """Multiplexing daemon that manages gitstatusd processes for all worktrees."""

    def __init__(self, config):
        from ..shared.config import Config

        self.config: Config = config
        logger.info(
            "Daemon configuration loaded - worktrees_dir: %s, github_repo: %s, git_fallbacks: %s",
            self.config.worktrees_dir_resolved,
            self.config.github_repo,
            self.config.enable_git_fallbacks,
        )
        logger.info(
            "GitHub refresh configuration - debounce_delay: %.1fs, periodic_interval: %.1fs",
            self.config.github_debounce_delay,
            self.config.github_periodic_interval,
        )

        # Initialize GitHub interface
        self.github_interface = None

        # Track daemon health state using proper protocol types
        from ..shared.protocol import DaemonHealth, DaemonHealthStatus

        self.daemon_health = DaemonHealth(
            status=DaemonHealthStatus.OK,
            last_error=None,
            last_error_time=None,
            github_errors=0,
            gitstatusd_errors=0,
        )
        if self.config.github_repo:
            try:
                from .github_client import GitHubInterface

                self.github_interface = GitHubInterface(self.config.github_repo)
                logger.info("GitHub interface initialized for repo: %s", self.config.github_repo)
            except Exception as e:
                logger.warning(
                    "Failed to initialize GitHub interface for %s: %s", self.config.github_repo, e
                )
        self.daemon_dir = self.config.daemon_dir
        self.socket_path = self.config.daemon_socket_file
        self.pid_file = self.config.daemon_pid_file

        # Managed state
        self.known_worktrees: Dict[Path, WorktreeInfo] = {}
        self.gitstatusd_processes: Dict[Path, GitStatusdProcess] = {}
        self.git_repo_manager = GitRepositoryManager()

        # Server state
        self.server: Optional[asyncio.Server] = None
        self.running = False
        self.discovery_task: Optional[asyncio.Task] = None

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
                and (datetime.now() - self.daemon_health.last_error_time).total_seconds() > 60
            ):
                self.daemon_health.status = DaemonHealthStatus.OK
                self.daemon_health.last_error = None
                self.daemon_health.last_error_time = None
                logger.info("Daemon health status cleared - operations are succeeding")

    def _find_gitstatusd(self) -> Optional[str]:
        """Find gitstatusd binary."""
        # Use config value if set
        if self.config.gitstatusd_path:
            gitstatusd_path = str(self.config.gitstatusd_path)
            try:
                result = subprocess.run(
                    [gitstatusd_path, "--version"], capture_output=True, timeout=2
                )
                if result.returncode == 0:
                    logger.info("Using configured gitstatusd at: %s", gitstatusd_path)
                    return gitstatusd_path
                else:
                    logger.error("Configured gitstatusd path not working: %s", gitstatusd_path)
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
                logger.error("Configured gitstatusd path failed: %s (%s)", gitstatusd_path, e)
                return None

        # Auto-detect from common locations
        candidates = [
            "gitstatusd",  # In PATH
            str(
                Path.home() / ".cache/gitstatus/gitstatusd-darwin-arm64"
            ),  # oh-my-zsh/powerlevel10k
            str(Path.home() / ".cache/gitstatus/gitstatusd-linux-x86_64"),  # Linux variant
            "/usr/local/bin/gitstatusd",
            "/opt/homebrew/bin/gitstatusd",
        ]

        for candidate in candidates:
            try:
                result = subprocess.run([candidate, "--version"], capture_output=True, timeout=2)
                if result.returncode == 0:
                    logger.info("Found gitstatusd at: %s", candidate)
                    return candidate
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                continue

        return None

    async def discover_worktrees(self) -> None:
        """Discover worktrees by scanning the filesystem."""
        worktrees_dir = self.config.worktrees_dir_resolved
        if not worktrees_dir.exists():
            return

        logger.debug("Scanning for worktrees in %s", worktrees_dir)

        current_worktrees = set()

        # Scan worktree directory
        for path in worktrees_dir.iterdir():
            if path.is_dir() and (path / ".git").exists():
                worktree_info = WorktreeInfo(path, path.name)
                current_worktrees.add(worktree_info)

                # Update existing or add new
                if path in self.known_worktrees:
                    self.known_worktrees[path].last_seen = time.time()
                else:
                    logger.info("Discovered new worktree: %s", path.name)
                    self.known_worktrees[path] = worktree_info
                    await self._start_gitstatusd_for_worktree(worktree_info)

        # Detect disappeared worktrees
        disappeared = set(self.known_worktrees.keys()) - {wt.path for wt in current_worktrees}

        for disappeared_path in disappeared:
            worktree_info = self.known_worktrees[disappeared_path]
            logger.info("Worktree disappeared: %s", worktree_info.name)
            await self._stop_gitstatusd_for_worktree(worktree_info)
            del self.known_worktrees[disappeared_path]

    async def _start_gitstatusd_for_worktree(self, worktree_info: WorktreeInfo) -> None:
        """Start gitstatusd for a worktree."""
        gitstatusd_path = self._find_gitstatusd()
        if not gitstatusd_path:
            logger.error(
                "gitstatusd binary not found, cannot start process for %s", worktree_info.name
            )
            return

        if worktree_info.path in self.gitstatusd_processes:
            return  # Already managed

        process = GitStatusdProcess(
            worktree_info,
            gitstatusd_path,
            self.config,
            self.git_repo_manager,
            self.github_interface,
            error_callback=self._record_error,
        )
        await process.start()
        self.gitstatusd_processes[worktree_info.path] = process

        logger.info(
            "Started gitstatusd for worktree %s (GitHub: %s)",
            worktree_info.name,
            "enabled" if self.github_interface else "disabled",
        )

    async def _stop_gitstatusd_for_worktree(self, worktree_info: WorktreeInfo) -> None:
        """Stop gitstatusd for a worktree."""
        process = self.gitstatusd_processes.get(worktree_info.path)
        if process:
            await process.stop()
            del self.gitstatusd_processes[worktree_info.path]
            logger.info("Stopped gitstatusd for worktree %s", worktree_info.name)

    async def _periodic_discovery(self) -> None:
        """Periodic discovery loop."""
        while self.running:
            try:
                await self.discover_worktrees()
                await asyncio.sleep(30)  # Discover every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic discovery: %s", e)
                await asyncio.sleep(30)

    async def handle_client_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
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
                error_response = create_error_response(ErrorCodes.PARSE_ERROR, f"Parse error: {e}")
                await self._send_response(writer, error_response)
                return

            # Trigger discovery to ensure we have up-to-date worktrees
            await self.discover_worktrees()

            # Handle different method types
            try:
                if method == "get_status":
                    response = await self._handle_status_request(request, start_time)
                elif method == "ping":
                    response = await self._handle_ping_request(request, start_time)
                elif method == "shutdown":
                    response = await self._handle_shutdown_request(request)
                else:
                    error_response = create_error_response(
                        ErrorCodes.METHOD_NOT_FOUND, f"Method '{method}' not found", request_id
                    )
                    await self._send_response(writer, error_response)
                    return

                # Send successful response
                await self._send_response(writer, response)

            except Exception as e:
                logger.error("Error handling method %s: %s", method, e)
                error_response = create_error_response(
                    ErrorCodes.INTERNAL_ERROR, f"Internal error: {e}", request_id
                )
                await self._send_response(writer, error_response)

        except Exception as e:
            logger.error("Error handling client request: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()

    def _create_success_response(self, result: Any, request_id: uuid.UUID) -> Response:
        """Create a successful JSON-RPC response."""
        return Response(result=result, id=request_id)

    async def _send_response(
        self, writer: asyncio.StreamWriter, response: Response | ErrorResponse
    ) -> None:
        """Send a JSON-RPC response to the client."""
        response_data = response.model_dump_json().encode()
        writer.write(response_data)
        writer.write(b"\n")
        await writer.drain()

    async def _handle_status_request(self, request: Request, start_time: float) -> Response:
        """Handle get_status JSON-RPC method."""
        try:
            # Parse parameters
            params = StatusParams.model_validate(request.params)
            worktree_paths = params.worktree_paths

            # If no paths specified, return all discovered worktrees
            if not worktree_paths:
                worktree_paths = list(self.known_worktrees.keys())
                logger.debug(
                    "No specific worktrees requested, returning all %d discovered",
                    len(worktree_paths),
                )

            # Always return unified StatusResponse (whether single or multiple worktrees)
            results = {}
            individual_times = {}

            # Process all worktrees concurrently
            async def process_single_worktree(worktree_path):
                single_start = time.time()
                process = self.gitstatusd_processes.get(worktree_path)

                if process:
                    (
                        dirty_files,
                        untracked_files,
                        commit_info_data,
                        ahead_behind,
                        branch_name,
                        pr_info_data,
                        last_updated_at,
                        is_cached,
                    ) = await process.get_comprehensive_status()
                    single_time = (time.time() - single_start) * 1000

                    # Create CommitInfo from the data with validation
                    commit_info = CommitInfo.model_validate(commit_info_data)

                    # Create PRInfo from the data if available
                    pr_info = None
                    if pr_info_data:
                        from ..shared.github_models import PRInfo

                        pr_info = PRInfo(
                            branch=branch_name,
                            github_pr=pr_info_data,  # Store the serializable dictionary data
                            gh_error=None,
                        )

                    worktree_info = self.known_worktrees.get(worktree_path)
                    worktree_name = worktree_info.name if worktree_info else worktree_path.name
                    is_main = worktree_path.resolve() == self.config.main_repo_resolved.resolve()

                    return (
                        str(worktree_path),
                        StatusResult(
                            worktree_path=str(worktree_path),
                            worktree_name=worktree_name,
                            branch=branch_name,
                            has_dirty_files=len(dirty_files) > 0,
                            has_untracked_files=len(untracked_files) > 0,
                            processing_time_ms=single_time,
                            last_updated_at=last_updated_at,
                            is_cached=is_cached,
                            commit_info=commit_info,
                            ahead_count=ahead_behind[0],
                            behind_count=ahead_behind[1],
                            is_main=is_main,
                            pr_info=pr_info,
                        ),
                        single_time,
                    )
                else:
                    logger.warning("Worktree not found: %s", worktree_path)
                    return str(worktree_path), None, 0

            # Run all worktree processing concurrently
            worktree_results = await asyncio.gather(
                *[process_single_worktree(worktree_path) for worktree_path in worktree_paths]
            )

            # Collect results from concurrent processing
            for path_str, status_result, single_time in worktree_results:
                if status_result:
                    results[path_str] = status_result
                    individual_times[path_str] = single_time

            total_time = (time.time() - start_time) * 1000
            status_response = StatusResponse(
                results=results,
                total_processing_time_ms=total_time,
                individual_processing_times_ms=individual_times,
                concurrent_requests=len(worktree_paths),
                daemon_health=self.daemon_health,
            )

            # Clear error status if operations are succeeding
            self._clear_errors_if_healthy()

            return self._create_success_response(status_response, request.id)

        except Exception as e:
            logger.error("Error in status request: %s", e)
            raise

    async def _handle_ping_request(self, request: Request, start_time: float) -> Response:
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

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting GitStatusd daemon for %s", self.config.main_repo_resolved)

        # Clean up old socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Start server
        self.server = await asyncio.start_unix_server(self.handle_client_request, self.socket_path)

        # Write PID file
        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))

        self.running = True

        # Start periodic discovery
        self.discovery_task = asyncio.create_task(self._periodic_discovery())

        # Initial discovery
        await self.discover_worktrees()

        logger.info("GitStatusd daemon started, listening on %s", self.socket_path)

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping GitStatusd daemon")

        self.running = False

        # Cancel discovery task
        if self.discovery_task:
            self.discovery_task.cancel()
            try:
                await self.discovery_task
            except asyncio.CancelledError:
                pass

        # Stop all gitstatusd processes
        for process in list(self.gitstatusd_processes.values()):
            await process.stop()

        self.gitstatusd_processes.clear()

        # Stop server
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up files
        if self.socket_path.exists():
            self.socket_path.unlink()
        if self.pid_file.exists():
            self.pid_file.unlink()

        logger.info("GitStatusd daemon stopped")


async def run_daemon(config) -> None:
    """Run the daemon with proper signal handling."""
    daemon = GitStatusdDaemon(config)

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
    from wt.shared.config import load_config

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
