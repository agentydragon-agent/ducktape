"""GitStatusd daemon client for fast working directory status.

This client connects to the GitStatusd multiplexing daemon via socket,
providing both low-level daemon communication and high-level status operations.
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from ..shared.protocol import (
    ErrorResponse,
    Request,
    Response,
    StatusParams,
    StatusResponse,
    WorktreeCreateParams,
    WorktreeCreateResult,
    WorktreeDeleteParams,
    WorktreeDeleteResult,
    WorktreeGetByNameParams,
    WorktreeGetByNameResult,
    WorktreeID,
    WorktreeIdentifyParams,
    WorktreeIdentifyResult,
    WorktreeListResult,
)

logger = logging.getLogger(__name__)


class WtClient:
    """JSON-RPC client for communicating with the worktree management daemon."""

    # Class-level lock to prevent multiple daemon startups
    _daemon_start_lock = asyncio.Lock()

    def __init__(self, config):
        from ..shared.configuration import Configuration

        self.config: Configuration = config

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

            return bool(psutil.pid_exists(pid) and self.config.daemon_socket_file.exists())

        except (ValueError, OSError):
            return False

    async def _start_daemon_if_needed(self) -> None:
        """Start daemon if not running."""

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
                                "wt.server.wt_server",
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

    async def get_status(self, worktree_ids: list[WorktreeID] | None = None) -> StatusResponse:
        """Get comprehensive status data from daemon for all specified worktree IDs.

        If worktree_ids is empty or None, returns status for all discovered worktrees.
        """
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = StatusParams(worktree_ids=worktree_ids or [])
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
                        f"Daemon status request failed: {error_response.error.message}",
                    )

                # Parse successful response - let Pydantic validate everything
                success_response = Response.model_validate(response_json)
                return StatusResponse.model_validate(success_response.result)


            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon status response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon status response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for status request: %s", e)
            raise RuntimeError(f"Daemon status communication failed: {e}")


    async def get_working_directory_status(
        self, worktree_path: Path,
    ) -> tuple[list[str], list[str]]:
        """Get working directory status for a single worktree (legacy compatibility method)."""
        # Use server-side identification to safely convert path to WorktreeID
        try:
            identify_result = await self.identify_worktree(str(worktree_path))
            status_response = await self.get_status([identify_result.wtid])
        except RuntimeError as e:
            # Only catch the specific error for unmanaged worktrees
            if "not a managed worktree" in str(e):
                return [], []
            # Let other RuntimeErrors (daemon communication failures, etc.) bubble up
            raise

        if not status_response.results:
            return [], []

        # Extract the single result
        result = next(iter(status_response.results.values()))

        # Convert boolean flags back to file lists for backward compatibility
        dirty_files = ["<files present>"] if result.has_dirty_files else []
        untracked_files = ["<files present>"] if result.has_untracked_files else []
        return dirty_files, untracked_files

    async def create_worktree(self, name: str, source_branch: str | None = None) -> WorktreeCreateResult:
        """Create a new worktree via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeCreateParams(name=name, source_branch=source_branch)
        request = Request(method="worktree_create", params=params.model_dump(), id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
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
                        f"Daemon worktree_create request failed: {error_response.error.message}",
                    )

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeCreateResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_create response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon worktree_create response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_create: %s", e)
            raise RuntimeError(f"Daemon worktree_create communication failed: {e}")

    async def delete_worktree(self, wtid: WorktreeID) -> WorktreeDeleteResult:
        """Delete a worktree via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeDeleteParams(wtid=wtid)
        request = Request(method="worktree_delete", params=params.model_dump(), id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
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
                        f"Daemon worktree_delete request failed: {error_response.error.message}",
                    )

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeDeleteResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_delete response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon worktree_delete response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_delete: %s", e)
            raise RuntimeError(f"Daemon worktree_delete communication failed: {e}")

    async def list_worktrees(self) -> WorktreeListResult:
        """List all worktrees via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = {}  # No parameters for list operation
        request = Request(method="worktree_list", params=params, id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
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
                        f"Daemon worktree_list request failed: {error_response.error.message}",
                    )

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeListResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_list response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon worktree_list response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_list: %s", e)
            raise RuntimeError(f"Daemon worktree_list communication failed: {e}")

    async def identify_worktree(self, absolute_path: str) -> WorktreeIdentifyResult:
        """Identify a worktree from its absolute path via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeIdentifyParams(absolute_path=absolute_path)
        request = Request(method="worktree_identify", params=params.model_dump(), id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
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
                        f"Daemon worktree_identify request failed: {error_response.error.message}",
                    )

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeIdentifyResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_identify response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon worktree_identify response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_identify: %s", e)
            raise RuntimeError(f"Daemon worktree_identify communication failed: {e}")

    async def get_worktree_by_name(self, name: str) -> WorktreeGetByNameResult:
        """Get a worktree by name via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeGetByNameParams(name=name)
        request = Request(method="worktree_get_by_name", params=params.model_dump(), id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
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
                        f"Daemon worktree_get_by_name request failed: {error_response.error.message}",
                    )

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeGetByNameResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_get_by_name response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(f"Failed to parse daemon worktree_get_by_name response: {e}")

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_get_by_name: %s", e)
            raise RuntimeError(f"Daemon worktree_get_by_name communication failed: {e}")
