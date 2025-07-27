"""GitStatusd daemon client for fast working directory status.

This client connects to the GitStatusd multiplexing daemon via socket,
providing both low-level daemon communication and high-level status operations.
"""

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from ..shared.protocol import (
    ErrorCodes,
    ErrorResponse,
    Request,
    Response,
    StatusParams,
    StatusResponse,
    StatusResult,
    create_error_response,
    parse_request,
)

logger = logging.getLogger(__name__)


class GitStatusdDaemonClient:
    """Client for communicating with GitStatusd multiplexing daemon."""

    # Class-level lock to prevent multiple daemon startups
    _daemon_start_lock = asyncio.Lock()

    def __init__(self, config):
        from ..shared.config import Config

        self.config: Config = config

        # Ensure daemon directory exists
        self.config.daemon_dir.mkdir(exist_ok=True)

    def _is_daemon_running(self) -> bool:
        """Check if the daemon is running."""
        try:
            if not self.config.daemon_pid_file.exists():
                return False

            with open(self.config.daemon_pid_file) as f:
                pid_str = f.read().strip()
                if not pid_str:
                    return False

                pid = int(pid_str)

            # Check if process exists and socket is accessible
            import psutil

            if psutil.pid_exists(pid) and self.config.daemon_socket_file.exists():
                return True
            else:
                return False

        except (ValueError, OSError):
            return False

    async def _start_daemon_if_needed(self) -> None:
        """Start daemon if not running."""
        # Validate WT_MAIN_REPO is set for daemon operation
        if not os.environ.get("WT_MAIN_REPO"):
            raise RuntimeError(
                "WT_MAIN_REPO environment variable must be set for daemon operation. "
                f"Run: export WT_MAIN_REPO={self.config.main_repo_resolved}"
            )

        async with self._daemon_start_lock:
            # Double-check after acquiring lock
            if self._is_daemon_running():
                logger.debug("Daemon already running for %s", self.config.main_repo_resolved)
                return

            logger.info("Starting wt daemon for %s", self.config.main_repo_resolved)
            logger.debug("Daemon socket: %s", self.config.daemon_socket_file)
            logger.debug("Daemon logs: %s", self.config.daemon_dir / "daemon.log")

            # Start daemon with simple fork+function call pattern
            await self._start_daemon_background()

            # Wait a bit for daemon to start up
            for _ in range(10):  # Wait up to 1 second
                await asyncio.sleep(0.1)
                if self._is_daemon_running():
                    logger.info("Daemon started successfully")
                    return

            logger.warning("Daemon may not have started properly")

    async def _start_daemon_background(self) -> None:
        """Start daemon in background using proper double-fork daemonization."""
        import os
        import sys

        # First fork - create intermediate process
        pid = os.fork()
        if pid == 0:
            # First child - create session leader and fork again
            try:
                # Become session leader
                os.setsid()

                # Second fork - ensure we can't regain controlling terminal
                pid = os.fork()
                if pid == 0:
                    # Second child - the actual daemon
                    try:
                        # Change to root directory to avoid keeping directories busy
                        os.chdir("/")

                        # Redirect stdin to /dev/null
                        null_fd = os.open("/dev/null", os.O_RDONLY)
                        os.dup2(null_fd, 0)  # stdin
                        os.close(null_fd)

                        # Redirect stdout/stderr to daemon log
                        log_file = self.config.daemon_dir / "daemon.log"
                        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                        os.dup2(log_fd, 1)  # stdout
                        os.dup2(log_fd, 2)  # stderr
                        os.close(log_fd)

                        # Exec daemon module directly (preserve environment)
                        os.execve(
                            sys.executable,
                            [
                                sys.executable,
                                "-m",
                                "wt.server.daemon",
                            ],
                            os.environ.copy(),
                        )
                    except Exception as e:
                        # This will go to daemon.log now
                        print(f"Daemon exec failed: {e}", file=sys.stderr)
                        os._exit(1)
                else:
                    # First child exits immediately
                    os._exit(0)
            except Exception as e:
                print(f"Daemon first fork failed: {e}", file=sys.stderr)
                os._exit(1)
        else:
            # Parent process - wait for first child to exit
            os.waitpid(pid, 0)
            logger.debug("Daemon daemonization completed (double-fork)")

    async def get_status(self, worktree_paths: list[Path]) -> StatusResponse:
        """Get comprehensive status data from daemon for all specified worktree paths.

        If worktree_paths is empty, returns status for all discovered worktrees.
        """
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = StatusParams(worktree_paths=worktree_paths)
        request = Request(method="get_status", params=params.model_dump(), id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")  # Add newline delimiter
            await writer.drain()

            # Read response
            response_data = await reader.readline()
            response_text = response_data.decode().strip()

            writer.close()
            await writer.wait_closed()

            # Parse and validate JSON-RPC response
            try:
                response_json = json.loads(response_text)

                # Check for error response first
                if "error" in response_json:
                    error_response = ErrorResponse.model_validate(response_json)
                    raise RuntimeError(
                        f"Daemon status request failed: {error_response.error.message}"
                    )

                # Parse successful response - let Pydantic validate everything
                success_response = Response.model_validate(response_json)
                status_response = StatusResponse.model_validate(success_response.result)

                return status_response

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon status response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon status response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for status request: %s", e)
            raise RuntimeError(f"Daemon status communication failed: {e}")

    async def get_all_worktree_status(self) -> dict[str, "WorktreeStatus"]:
        """Get comprehensive status for all worktrees converted to WorktreeStatus objects."""
        from ..server.git_manager import GitRepositoryManager
        from ..shared.git_interface import WorktreeStatus
        from ..shared.models import CommitInfo as ModelCommitInfo

        # Get all comprehensive status from daemon
        daemon_response = await self.get_status([])

        # Get default branch for status objects
        git_repo_manager = GitRepositoryManager()
        default_branch = git_repo_manager.get_default_branch(self.config.main_repo_resolved)

        # Convert daemon response to WorktreeStatus objects
        status_data = {}
        for worktree_path_str, result in daemon_response.results.items():
            try:
                # Convert dirty/untracked files from boolean flags back to lists for compatibility
                # TODO: Update WorktreeStatus to use boolean flags directly
                dirty_files = ["(has changes)"] if result.has_dirty_files else []
                untracked_files = ["(has untracked)"] if result.has_untracked_files else []

                # Create commit info from daemon response
                commit_info = ModelCommitInfo(
                    last_commit=result.commit_info.short_hash,
                    last_commit_message=result.commit_info.message,
                    last_commit_author=result.commit_info.author,
                    last_commit_date=datetime.fromisoformat(
                        result.commit_info.date.replace("Z", "+00:00")
                    ),
                )

                # Extract PR info from daemon response
                pr_info = result.pr_info  # Use existing PRInfo type directly

                status_data[result.worktree_name] = WorktreeStatus(
                    name=result.worktree_name,
                    branch=result.branch,
                    ahead=result.ahead_count,
                    behind=result.behind_count,
                    dirty_files=dirty_files,
                    untracked_files=untracked_files,
                    default_branch=default_branch,
                    commit_info=commit_info,
                    pr_info=pr_info,  # GitHub PR info from daemon
                )
            except Exception as e:
                logger.warning("Failed to process daemon status for %s: %s", worktree_path_str, e)
                # Create fallback status
                status_data[result.worktree_name] = WorktreeStatus(
                    name=result.worktree_name,
                    branch=result.branch,
                    ahead=0,
                    behind=0,
                    dirty_files=[],
                    untracked_files=[],
                    default_branch=default_branch,
                    commit_info=ModelCommitInfo(),
                    pr_info=None,
                )

        return status_data

    async def get_working_directory_status(
        self, worktree_path: Path
    ) -> Tuple[list[str], list[str]]:
        """Get working directory status for a single worktree (legacy compatibility method)."""
        status_response = await self.get_status([worktree_path])

        if not status_response.results:
            return [], []

        # Extract the single result
        result = list(status_response.results.values())[0]

        # Convert boolean flags back to file lists for backward compatibility
        dirty_files = ["<files present>"] if result.has_dirty_files else []
        untracked_files = ["<files present>"] if result.has_untracked_files else []
        return dirty_files, untracked_files
