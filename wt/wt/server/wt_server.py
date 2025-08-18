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
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..shared.configuration import Configuration, load_config
from ..shared.protocol import (
    DaemonHealth,
    DaemonHealthStatus,
    ErrorCodes,
    ErrorResponse,
    PingResult,
    Request,
    Response,
    WorktreeID,
    create_error_response,
    parse_request,
)
from .discovery_scanner import DiscoveryScanner
from .git_manager import GitManager
from .github_client import GitHubInterface
from .gitstatus_refresh import DebouncedGitstatusRefresh
from .gitstatusd_listener import (
    GitstatusdListener,
    GitStatusdProtocol,
    GitStatusdRequest,
    gitstatusd_response_to_legacy_format,
)

# Force import of handlers to register RPC methods
from .handlers import (
    path_handler,  # noqa: F401
    status_handler,  # noqa: F401
    worktree_handler,  # noqa: F401
)
from .pr_service import PRService
from .repo_status import RepoStatus
from .rpc import rpc
from .types import DiscoveredWorktree
from .worktree_index import WorktreeIndex
from .worktree_registry import WorktreeRegistry
from .worktree_service import WorktreeService

logger = logging.getLogger(__name__)


def write_startup_handshake(
    success: bool,
    error_message: str | None = None,
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
        return
    with contextlib.suppress(OSError):
        os.write(handshake_fd, payload)

    if redirect_after:
        try:
            daemon_log = load_config().wt_dir / "daemon.log"
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


class GitstatusdClient:
    def __init__(
        self,
        worktree_info: DiscoveredWorktree,
        config,
        git_manager: GitManager,
        error_callback=None,
    ):
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
            response = await self.process.stdout.readuntil(b"\x1e")
            response_str = response.decode("utf-8")
            parsed_response = GitStatusdProtocol.parse_response(response_str)
            dirty_files, untracked_files = gitstatusd_response_to_legacy_format(
                parsed_response,
            )
            self.cached_working_status = (dirty_files, untracked_files)
            self.last_updated_at = datetime.now()
        except Exception:
            logger.exception("gitstatusd update failed for %s", self.worktree_info.name)
            if not self.last_updated_at:
                self.last_updated_at = datetime.now()
            # Mark failure by clearing cache and letting state be STOPPED/FAILED next check
            self.cached_working_status = ([], [])
        finally:
            self._status_updating = False

    def get_cached_working_status(
        self,
    ) -> tuple[list[str], list[str], datetime | None, bool]:
        if self.cached_working_status and self.last_updated_at:
            df, uf = self.cached_working_status
            return df, uf, self.last_updated_at, True
        return [], [], None, False

    # Old _parse_response method removed - now using GitStatusdProtocol


class WtDaemon:
    """Main worktree management daemon that handles all worktree operations."""

    def __init__(self, config):
        self.config: Configuration = config
        logger.info(
            "Daemon configuration loaded - worktrees_dir: %s, github_repo: %s",
            self.config.worktrees_dir,
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

        self.daemon_health = DaemonHealth(
            status=DaemonHealthStatus.OK,
            last_error=None,
            last_error_time=None,
            github_errors=0,
            gitstatusd_errors=0,
        )
        # use self.config.wt_dir directly
        self.socket_path = self.config.daemon_socket_path
        self.pid_file = self.config.daemon_pid_path

        # Managed state
        self.known_worktrees: dict[Path, DiscoveredWorktree] = {}
        self.worktree_index: WorktreeIndex | None = None
        self.gitstatusd_clients: dict[WorktreeID, GitstatusdListener] = {}
        self.pr_services: dict[WorktreeID, PRService] = {}
        self.git_watchers: dict[WorktreeID, DebouncedGitstatusRefresh] = {}
        self._state_lock = asyncio.Lock()
        self.git_manager = GitManager(config=self.config)
        self.repo_status = RepoStatus(self.git_manager, self.config)
        self.worktree_service = WorktreeService(self.git_manager, self.github_interface)
        # Build DI services
        from .services import (
            DiscoveryService,
            GitService,
            GitstatusdService,
            HealthService,
            PRServiceProvider,
            StatusService,
            WorktreeCoordinator,
            WorktreeIndexService,
        )

        self.git_service = GitService(self.git_manager)
        self.index_service = WorktreeIndexService(
            get_index=lambda: self.worktree_index,
            rebuild_index=lambda: self.rebuild_index(),
            run_discovery_once=lambda: self._run_discovery_once(),
        )
        self.gitstatusd_service = GitstatusdService(
            get_client=lambda p: (
                self.gitstatusd_clients.get(self.known_worktrees[p].wtid)  # type: ignore[return-value]
                if p in self.known_worktrees
                else None
            ),
            iter_client_paths=lambda: list(self.known_worktrees.keys()),
            ensure_watcher_for_path=lambda p: (
                self._ensure_git_watcher(self.known_worktrees[p])
                if p in self.known_worktrees
                else asyncio.sleep(0)
            ),
            list_watchers=lambda: list(self.git_watchers.values()),
            clear_watchers=lambda: self.git_watchers.clear(),
        )
        self.pr_provider = PRServiceProvider(services=self.pr_services)
        self.status_service = StatusService(self.repo_status)
        self.discovery_service = DiscoveryService(
            lambda: self.discovery_scanning,
            periodic=lambda: self._periodic_discovery_wrapper(),
            cancel_periodic=lambda: self._cancel_periodic_discovery(),
        )
        self.health_service = HealthService(lambda: self.daemon_health)
        self.coordinator = WorktreeCoordinator(
            register_fn=self._register_worktree,
            unregister_fn=self._unregister_worktree,
        )

        # Server state
        self.server: asyncio.Server | None = None
        self.running = False
        self.discovery_task: asyncio.Task | None = None
        self.discovery_scanning: bool = False
        self.discovery_scanner = DiscoveryScanner()
        self.registry = WorktreeRegistry()
        self._startup_tasks: list[asyncio.Task] = []

        def _shared_async_run(awaitable):
            return asyncio.get_event_loop().run_until_complete(awaitable)

        self.shared_async_run = _shared_async_run

        # Ensure daemon directory exists
        self.config.wt_dir.mkdir(exist_ok=True)

        # Defer initial discovery to start() to avoid running async in __init__
        self.known_worktrees = {}
        self.worktree_index = None

        self._method_handlers = rpc
        with contextlib.suppress(Exception):
            logger.info("Registered RPC methods: %s", sorted(rpc.list_methods()))

    def _record_error(self, error_type: str, error_message: str):
        """Record an error and update daemon health status."""

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

        if (
            self.daemon_health.status == DaemonHealthStatus.ERROR
            and self.daemon_health.last_error_time
            and (datetime.now() - self.daemon_health.last_error_time).total_seconds()
            > 60
        ):
            self.daemon_health.status = DaemonHealthStatus.OK
            self.daemon_health.last_error = None
            self.daemon_health.last_error_time = None
            logger.info("Daemon health status cleared - operations are succeeding")

    def _validate_gitstatusd(self) -> tuple[str | None, str | None]:
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
        if not self.config.main_repo.exists() or not self.config.main_repo.is_dir():
            errors.append(
                f"Main repository is not a directory: {self.config.main_repo}",
            )

        # Check if main repo is actually a git repository
        git_dir = self.config.main_repo / ".git"
        if not git_dir.exists():
            errors.append(
                f"Main repository is not a git repository (no .git directory): {self.config.main_repo}",
            )

        # Check worktrees directory can be created
        worktrees_dir = self.config.worktrees_dir
        if worktrees_dir.exists() and not worktrees_dir.is_dir():
            errors.append(
                f"Worktrees directory path exists but is not a directory: {worktrees_dir}",
            )

        # Check daemon directory permissions
        try:
            self.config.wt_dir.mkdir(exist_ok=True)
        except PermissionError:
            errors.append(
                f"Cannot create daemon directory (permission denied): {self.config.wt_dir}",
            )
        except Exception as e:
            errors.append(f"Cannot create daemon directory: {self.config.wt_dir} ({e})")

        # Validate GitHub configuration if enabled
        if self.config.github_enabled and not self.config.github_repo:
            errors.append("GitHub is enabled but github_repo is not configured")

        if errors:
            return "Configuration validation failed:\n" + "\n".join(
                f"  - {error}" for error in errors
            )

        return None

    async def _start_gitstatusd_for_worktree(
        self,
        worktree_info: DiscoveredWorktree,
    ) -> None:
        """Start gitstatusd for a worktree."""
        gitstatusd_path = self._find_gitstatusd()
        if not gitstatusd_path:
            logger.error(
                "gitstatusd binary not found, cannot start process for %s",
                worktree_info.name,
            )
            return

        if worktree_info.wtid in self.gitstatusd_clients:
            # Ensure watcher exists
            if worktree_info.wtid not in self.git_watchers:
                await self._ensure_git_watcher(worktree_info)
            return
        gs_client = GitstatusdListener(
            worktree_info,
            self.config,
            self.git_manager,
            error_callback=self._record_gitstatusd_error,
        )
        await gs_client.start()
        # Kick an initial nonblocking refresh; watcher/poll keeps it fresh
        self._initial_status_task = asyncio.create_task(
            gs_client.update_working_status(),
        )
        self.gitstatusd_clients[worktree_info.wtid] = gs_client
        prsvc = PRService(
            self.github_interface,
            self.config,
            worktree_info,
            self.git_manager,
        )
        await prsvc.start()
        self.pr_services[worktree_info.wtid] = prsvc

        # Start .git watcher to drive status updates
        await self._ensure_git_watcher(worktree_info)

        logger.info(
            "Started gitstatusd for worktree %s (GitHub: %s)",
            worktree_info.name,
            "enabled" if self.github_interface else "disabled",
        )

    async def _stop_gitstatusd_for_worktree(
        self,
        worktree_info: DiscoveredWorktree,
    ) -> None:
        """Stop gitstatusd for a worktree."""
        gs_client = self.gitstatusd_clients.get(worktree_info.wtid)
        if gs_client:
            await gs_client.stop()
            del self.gitstatusd_clients[worktree_info.wtid]
            logger.info("Stopped gitstatusd for worktree %s", worktree_info.name)
        prsvc = self.pr_services.get(worktree_info.wtid)
        if prsvc:
            await prsvc.stop()
            del self.pr_services[worktree_info.wtid]
        watcher = self.git_watchers.get(worktree_info.wtid)
        if watcher:
            await watcher.stop()
            del self.git_watchers[worktree_info.wtid]

    async def _run_discovery_once(self) -> None:
        self.discovery_scanning = True
        try:
            current = await self.discovery_scanner.scan(self.config.worktrees_dir)
            changes = self.registry.apply(current)
            async with self._state_lock:
                self.known_worktrees = dict(self.registry.known)
                self.worktree_index = WorktreeIndex.build(
                    self.known_worktrees.values(),
                    self.config.main_repo,
                )
        finally:
            self.discovery_scanning = False
        for wt in changes.added:
            await self._start_gitstatusd_for_worktree(wt)
        for wt in changes.removed:
            await self._stop_gitstatusd_for_worktree(wt)

    async def _periodic_discovery(self) -> None:
        while self.running:
            try:
                await self._run_discovery_once()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in periodic discovery")
                await asyncio.sleep(30)

    async def _periodic_discovery_wrapper(self) -> None:
        if self.discovery_task and not self.discovery_task.done():
            return
        self.discovery_task = asyncio.create_task(self._periodic_discovery())

    def _cancel_periodic_discovery(self) -> None:
        if self.discovery_task:
            self.discovery_task.cancel()

    async def handle_client_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client request using JSON-RPC 2.0 protocol."""
        start_time = datetime.now()

        try:
            # Read request line
            data = await reader.readline()
            if not data:
                return

            # Parse JSON-RPC request
            request = parse_request(data.decode().strip())
            request_id = request.id
            method = request.method
            logger.info("Handling JSON-RPC request %s: %s", request_id, method)

            # Kick discovery opportunistically but do not block request handling
            if not self.known_worktrees and not self.discovery_scanning:
                self._discovery_kick = asyncio.create_task(self._run_discovery_once())

            # Handle request via RPC registry only
            response = await self._method_handlers.dispatch(
                request,
                self,
                writer,
                start_time,
            )  # type: ignore[attr-defined]
            await self._send_response(writer, response)
            return

        except Exception:
            logger.exception("Error handling client request")
            rid = (
                request.id if ("request" in locals() and request) else uuid.UUID(int=0)
            )
            with contextlib.suppress(Exception):
                await self._send_response(
                    writer,
                    create_error_response(
                        ErrorCodes.INTERNAL_ERROR,
                        "Internal server error",
                        rid,
                    ),
                )
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

    async def _handle_ping_request(
        self,
        request: Request,
        start_time: datetime,
    ) -> Response:
        """Handle ping JSON-RPC method."""
        result = PingResult(
            daemon_pid=os.getpid(),
            started_at=start_time,
            discovered_worktrees=list(self.known_worktrees.keys()),
        )
        return self._create_success_response(result, request.id)

    async def _handle_shutdown_request(
        self,
        request: Request,
        start_time: datetime | None = None,
    ) -> Response:
        """Handle shutdown JSON-RPC method."""
        logger.info("Received shutdown request")
        self._shutdown_task = asyncio.create_task(self.stop())
        return self._create_success_response("shutting down", request.id)

    async def _ensure_git_watcher(self, worktree_info: DiscoveredWorktree) -> None:
        if worktree_info.wtid in self.git_watchers:
            return
        gs_client = self.gitstatusd_clients.get(worktree_info.wtid)
        if not gs_client:
            return

        async def _cb(reason: str):
            await gs_client.update_working_status()

        watcher = DebouncedGitstatusRefresh(worktree_info.path, _cb, debounce_delay=0.5)
        await watcher.start()
        self.git_watchers[worktree_info.wtid] = watcher

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting wt daemon for %s", self.config.main_repo)

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

        # Post-creation script is validated at use-time in WorktreeService

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
        self.pid_file.write_text(str(os.getpid()))
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

        logger.info("wt daemon started, listening on %s", self.socket_path)

        # Start long-running service loops
        await self.discovery_service.start()
        await self.pr_provider.start()
        await self.gitstatusd_service.start()

        # Kick an initial discovery (non-blocking) to seed state early
        self._discovery_kick = asyncio.create_task(self._run_discovery_once())

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping wt daemon")

        self.running = False

        # Stop long-running service loops
        await self.gitstatusd_service.stop()
        await self.pr_provider.stop()
        await self.discovery_service.stop()

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

    async def rebuild_index(self) -> None:
        async with self._state_lock:
            self.worktree_index = WorktreeIndex.build(
                self.known_worktrees.values(),
                self.config.main_repo,
            )

    async def _register_worktree(self, info: DiscoveredWorktree) -> None:
        async with self._state_lock:
            self.known_worktrees[info.path] = info
        await self._start_gitstatusd_for_worktree(info)
        await self.rebuild_index()

    async def _unregister_worktree(self, info: DiscoveredWorktree) -> None:
        await self._stop_gitstatusd_for_worktree(info)
        async with self._state_lock:
            self.known_worktrees.pop(info.path, None)
        await self.rebuild_index()


async def run_daemon(config) -> None:
    """Run the daemon with proper signal handling."""
    daemon = WtDaemon(config)

    # Signal handling
    def signal_handler():
        logger.info("Received shutdown signal")
        daemon._shutdown_task = asyncio.create_task(daemon.stop())

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
    # Load config using the standard discovery system
    config = load_config()

    # Configure logging to write only to daemon log file
    daemon_dir = config.wt_dir
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
