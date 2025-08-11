"""wt daemon client for fast working directory status.

This client connects to the wt multiplexing daemon via socket,
providing both low-level daemon communication and high-level status operations.
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import psutil
from pydantic import TypeAdapter

from ..shared.configuration import Configuration
from ..shared.error_handling import validate_worktree_name
from ..shared.protocol import (
    ErrorResponse,
    Request,
    Response,
    StartupMessage,
    StatusParams,
    StatusResponse,
    TeleportCdThere,
    TeleportDoesNotExist,
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
    WorktreeResolvePathParams,
    WorktreeResolvePathResult,
    WorktreeTeleportTargetParams,
)
from .shell_utils import emit_command

logger = logging.getLogger(__name__)

    


class WtClient:
    """JSON-RPC client for communicating with the worktree management daemon."""

    def emit_cd_command(self, dest_repo: Path, config) -> None:
        current_wt, rel_path = self._get_current_worktree_info(config)
        if rel_path and current_wt:
            target_subpath = dest_repo / rel_path
            dest_path = target_subpath if target_subpath.exists() and target_subpath.is_dir() else dest_repo
        else:
            dest_path = dest_repo
        emit_command(f"cd {shlex.quote(str(dest_path))}")

    def _get_current_worktree_info(self, config) -> tuple[Path | None, str | None]:
        cwd = Path.cwd()
        worktrees_dir = config.worktrees_dir_resolved
        if cwd.is_relative_to(worktrees_dir):
            for parent in [cwd, *list(cwd.parents)]:
                if parent.parent == worktrees_dir:
                    try:
                        rel_path = cwd.relative_to(parent)
                        return parent, str(rel_path) if str(rel_path) != "." else None
                    except ValueError:
                        return parent, None
        main_repo = config.main_repo_resolved
        if cwd.is_relative_to(main_repo):
            if cwd == main_repo:
                return main_repo, None
            try:
                rel_path = cwd.relative_to(main_repo)
                return main_repo, str(rel_path)
            except ValueError:
                pass
        return None, None

    # Class-level lock to prevent multiple daemon startups
    _daemon_start_lock = asyncio.Lock()

    def __init__(self, config, verbose: bool = False):
        self.config: Configuration = config
        self.verbose: bool = bool(verbose)

        # Handshake pipe FD (used during startup); None when inactive
        self._handshake_pipe: int | None = None

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
            return bool(
                psutil.pid_exists(pid) and self.config.daemon_socket_file.exists(),
            )

        except (ValueError, OSError):
            return False

    async def _start_daemon_if_needed(self) -> None:
        """Start daemon if not running."""

        async with self._daemon_start_lock:
            # Double-check after acquiring lock
            if self._is_daemon_running():
                logger.debug(
                    "Daemon already running for %s",
                    self.config.main_repo_resolved,
                )
                return

            logger.info("Starting wt daemon for %s", self.config.main_repo_resolved)
            logger.debug("Daemon socket: %s", self.config.daemon_socket_file)
            logger.debug("Daemon logs: %s", self.config.daemon_dir / "daemon.log")
            if self.verbose:
                logger.info("wt: starting daemon … (%s)", self.config.daemon_socket_file)

            # Start daemon with simple fork+function call pattern
            await self._start_daemon_background()

            # Wait for handshake confirmation from daemon via pipe
            try:
                # Read handshake from pipe with timeout
                loop = asyncio.get_event_loop()
                # Emit immediate progress if verbose
                if self.verbose:
                    logger.info("wt: waiting for daemon handshake…")
                # Start a single background reader; don't create multiple competing readers
                reader_future = loop.run_in_executor(None, self._read_handshake_from_pipe)
                # Bound the time we wait before surfacing any progress
                first_wait = min(1.0, self.config.startup_timeout.total_seconds())
                try:
                    handshake_data = await asyncio.wait_for(reader_future, timeout=first_wait)
                except asyncio.TimeoutError:
                    if self.verbose:
                        logger.info("wt: daemon is starting… waiting for ready signal")
                    # Keep waiting up to the remaining timeout
                    remaining = max(
                        0.0,
                        self.config.startup_timeout.total_seconds() - first_wait,
                    )
                    handshake_data = await asyncio.wait_for(reader_future, timeout=remaining if remaining > 0 else 0.1)

                # Check protocol version
                protocol_version = handshake_data.get("protocol_version", 0)
                if protocol_version != 1:
                    raise RuntimeError(
                        f"Incompatible daemon protocol version {protocol_version}, expected 1",
                    )

                if handshake_data.get("success"):
                    pid = handshake_data.get("pid")
                    if self.verbose:
                        logger.info("wt daemon: startup handshake ok (pid %s)", pid)
                    logger.info("Daemon startup handshake received from PID %d", pid)

                    # Verify daemon is actually running and accessible
                    if self._is_daemon_running():
                        logger.info(
                            "Daemon started successfully with handshake confirmation",
                        )
                        return
                    logger.warning("Got successful handshake but daemon not accessible")
                    raise RuntimeError(
                        "Daemon handshake successful but daemon not accessible",
                    )
                # Daemon startup failed - show error to user
                error_message = handshake_data.get("error", "Unknown startup error")
                raise RuntimeError(f"Daemon startup failed:\n{error_message}")

            except asyncio.TimeoutError:
                timeout_secs = self.config.startup_timeout.total_seconds()
                logger.warning(
                    "Daemon startup timed out - no handshake received within %.1f seconds",
                    timeout_secs,
                )
                if self.verbose:
                    logger.info("wt daemon: startup timed out after %.1fs", timeout_secs)
                raise RuntimeError(
                    f"Daemon startup timed out after {timeout_secs:.1f} seconds",
                )
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Daemon handshake contains invalid JSON: {e}")
            except Exception as e:
                diag = []
                try:
                    daemon_log = self.config.daemon_dir / "daemon.log"
                    diag.append(f"daemon.log: {daemon_log}")
                    if daemon_log.exists():
                        tail = daemon_log.read_text(errors="ignore").splitlines()[-50:]
                        diag.append("daemon.log (tail):\n" + "\n".join(tail))
                except Exception:
                    pass
                try:
                    diag.append(f"pid file exists: {self.config.daemon_pid_file.exists()}")
                    if self.config.daemon_pid_file.exists():
                        diag.append(f"pid file contents: {self.config.daemon_pid_file.read_text().strip()}")
                    diag.append(f"socket exists: {self.config.daemon_socket_file.exists()}")
                except Exception:
                    pass
                raise RuntimeError("Daemon startup failed.\n" + "\n".join(diag)) from e
            finally:
                # Mark pipe as inactive (reader thread closes underlying FD)
                self._handshake_pipe = None

    async def _start_daemon_background(self) -> None:
        """Start daemon in background using proper double-fork daemonization."""

        # Create pipe for handshake communication (dedicated FD, not stdout)
        handshake_read, handshake_write = os.pipe()
        try:
            os.set_inheritable(handshake_write, True)
        except Exception:
            pass

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

                        # Close read end of pipe in daemon process
                        os.close(handshake_read)

                        # Redirect stdout and stderr to daemon log; keep handshake_write inherited
                        log_file = self.config.daemon_dir / "daemon.log"
                        log_fd = os.open(
                            log_file,
                            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                            0o644,
                        )
                        os.dup2(log_fd, 1)
                        os.dup2(log_fd, 2)
                        os.close(log_fd)

                        # Exec daemon module; pass handshake FD via env
                        env = os.environ.copy()
                        env["WT_HANDSHAKE_FD"] = str(handshake_write)
                        try:
                            from pathlib import Path as _P
                            project_root = str(_P(__file__).resolve().parents[2])
                            existing = env.get("PYTHONPATH", "")
                            env["PYTHONPATH"] = f"{project_root}:{existing}" if existing else project_root
                        except Exception:
                            pass
                        os.execve(
                            sys.executable,
                            [
                                sys.executable,
                                "-m",
                                "wt.server.wt_server",
                            ],
                            env,
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

            # Close write end of pipe in parent
            os.close(handshake_write)

            # Store read pipe for handshake reading
            self._handshake_pipe = handshake_read

    def _read_handshake_from_pipe(self) -> dict:
        """Read streaming JSON handshake/progress until ready or failure.

        The daemon emits multiple JSON lines:
        - initial {success=True, phase="starting"}
        - progress {success=True, phase=..., discovered_worktrees=N}
        - final    {success=True, ready=True, ...}
        or a single failure {success=False, error=...}
        """

        if self._handshake_pipe is None:
            raise RuntimeError("No handshake pipe available")

        with os.fdopen(self._handshake_pipe, "r") as pipe_file:
            last_obj = None
            while True:
                line = pipe_file.readline()
                if not line:
                    if last_obj:
                        return last_obj
                    raise RuntimeError("Daemon closed handshake pipe before ready")
                if self.verbose:
                    print(f"[daemon-handshake] {line.rstrip()}")
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = StartupMessage.model_validate_json(line)
                except Exception:
                    continue
                last_obj = obj.model_dump()
                if not obj.success:
                    return last_obj
                if obj.ready:
                    return last_obj

    async def get_status(
        self,
        worktree_ids: list[WorktreeID] | None = None,
    ) -> StatusResponse:
        """Get comprehensive status data from daemon for all specified worktree IDs.

        If worktree_ids is empty or None, returns status for all discovered worktrees.
        """
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = StatusParams(
            worktree_ids=[wtid for wtid in (worktree_ids or []) if wtid is not None],
        )
        request = Request(
            method="get_status",
            params=params.model_dump(),
            id=request_id,
        )

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_file,
            )

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
                    # Surface daemon error directly
                    raise RuntimeError(error_response.error.message)

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
        self,
        worktree_path: Path,
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

    async def create_worktree(
        self,
        name: str,
        source_wtid: WorktreeID | None = None,
    ) -> WorktreeCreateResult:
        """Create a new worktree via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeCreateParams(name=name, source_wtid=source_wtid)
        request = Request(
            method="worktree_create",
            params=params.model_dump(),
            id=request_id,
        )

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_file,
            )

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
            await writer.drain()

            hook_stdout = []
            hook_stderr = []
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode().strip()
                try:
                    obj = json.loads(text)
                    if obj.get("event") == "hook_output":
                        stream = obj.get("stream")
                        data = obj.get("data", "")
                        if stream == "stdout":
                            hook_stdout.append(data)
                        else:
                            hook_stderr.append(data)
                        continue
                    response_json = obj
                except json.JSONDecodeError:
                    continue
                break

            writer.close()
            await writer.wait_closed()

            try:
                if "error" in response_json:
                    error_response = ErrorResponse.model_validate(response_json)
                    raise RuntimeError(error_response.error.message)
                success_response = Response.model_validate(response_json)
                result = WorktreeCreateResult.model_validate(success_response.result)
                if result.post_hook:
                    # Non-zero exit code => fail
                    if result.post_hook.exit_code and result.post_hook.exit_code != 0:
                        out = (result.post_hook.stdout or "") + ("\n" if result.post_hook.stdout else "") + (result.post_hook.stderr or "")
                        if out.strip():
                            print(out)
                        raise RuntimeError(
                            f"Post-creation script failed with exit code {result.post_hook.exit_code}",
                        )
                    # Execution error surfaced by server (e.g. script disappeared)
                    if result.post_hook.error:
                        out = (result.post_hook.stdout or "") + ("\n" if result.post_hook.stdout else "") + (result.post_hook.stderr or "")
                        if out.strip():
                            print(out)
                        raise RuntimeError(
                            f"Post-creation script error: {result.post_hook.error}",
                        )
                    # Ran flag false (e.g. not_found/not_file in legacy path) => fail
                    if not result.post_hook.ran:
                        out = (result.post_hook.stdout or "") + ("\n" if result.post_hook.stdout else "") + (result.post_hook.stderr or "")
                        if out.strip():
                            print(out)
                        raise RuntimeError("Post-creation script did not run")
                return result
            except Exception as e:
                logger.error("Failed to parse daemon worktree_create response: %s", e)
                raise

        except Exception as e:
            logger.error("Failed to communicate with daemon for worktree_create: %s", e)
            raise

    async def delete_worktree(self, wtid: WorktreeID) -> WorktreeDeleteResult:
        """Delete a worktree via RPC."""
        await self._start_daemon_if_needed()

        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")

        # Create JSON-RPC request
        request_id = uuid.uuid4()
        params = WorktreeDeleteParams(wtid=wtid)
        request = Request(
            method="worktree_delete",
            params=params.model_dump(),
            id=request_id,
        )

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_file,
            )

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
                    raise RuntimeError(error_response.error.message)

                # Parse successful response
                success_response = Response.model_validate(response_json)
                return WorktreeDeleteResult.model_validate(success_response.result)

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response from daemon: {e}")
            except Exception as e:
                logger.error("Failed to parse daemon worktree_delete response: %s", e)
                logger.error("Raw response: %s", response_text[:200])
                raise RuntimeError(
                    f"Failed to parse daemon worktree_delete response: {e}",
                )

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
        params: dict[str, object] = {}
        request = Request(method="worktree_list", params=params, id=request_id)

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_file,
            )

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
                raise RuntimeError(
                    f"Failed to parse daemon worktree_list response: {e}",
                )

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
        request = Request(
            method="worktree_identify",
            params=params.model_dump(),
            id=request_id,
        )

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_file,
            )

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
                raise RuntimeError(
                    f"Failed to parse daemon worktree_identify response: {e}",
                )

        except Exception as e:
            logger.error(
                "Failed to communicate with daemon for worktree_identify: %s",
                e,
            )
            raise RuntimeError(f"Daemon worktree_identify communication failed: {e}")

    async def get_worktree_by_name(self, name: str) -> WorktreeGetByNameResult:
        return await self._rpc("worktree_get_by_name", WorktreeGetByNameParams(name=name), WorktreeGetByNameResult)

    async def _rpc(self, method: str, params_model, result_model):
        await self._start_daemon_if_needed()
        if not self.config.daemon_socket_file.exists():
            raise RuntimeError("Daemon socket not available")
        req = Request(method=method, params=params_model.model_dump(), id=uuid.uuid4())
        try:
            reader, writer = await asyncio.open_unix_connection(self.config.daemon_socket_file)
            writer.write(req.model_dump_json().encode()); writer.write(b"\n"); await writer.drain()
            data = await reader.readline(); text = data.decode().strip()
            writer.close(); await writer.wait_closed()
            obj = json.loads(text)
            if "error" in obj:
                err = ErrorResponse.model_validate(obj)
                raise RuntimeError(err.error.message)
            resp = Response.model_validate(obj)
            adapter = TypeAdapter(result_model)
            return adapter.validate_python(resp.result)
        except Exception as e:
            logger.error("RPC %s failed: %s", method, e)
            raise

    async def resolve_path(self, params: WorktreeResolvePathParams) -> str:
        result = await self._rpc("worktree_resolve_path", params, WorktreeResolvePathResult)
        return result.absolute_path

    async def resolve_path_simple(self, worktree_name: str | None, path_spec: str) -> Path:
        params = WorktreeResolvePathParams(
            worktree_name=worktree_name,
            path_spec=path_spec,
            current_path=str(Path.cwd()),
        )
        return Path(await self.resolve_path(params))

    async def teleport_target(self, target_name: str, current_path: str) -> TeleportCdThere | TeleportDoesNotExist:
        return await self._rpc(
            "worktree_teleport_target",
            WorktreeTeleportTargetParams(target_name=target_name, current_path=current_path),
            TeleportResult,
        )

    async def require_worktree_exists(self, name: str) -> Path:
        res = await self.get_worktree_by_name(name)
        if not res.exists or not res.absolute_path:
            raise RuntimeError(f"Worktree '{name}' not found")
        return Path(res.absolute_path)

    async def create_worktree_convenience(
        self,
        name: str,
        *,
        source_name: str | None = None,
        from_default: bool = True,
    ) -> Path:
        validate_worktree_name(name)
        if source_name is not None:
            src = await self.get_worktree_by_name(source_name)
            if not src.exists or not src.wtid:
                raise RuntimeError(f"Worktree '{source_name}' not found")
            result = await self.create_worktree(name, source_wtid=src.wtid)
            return Path(result.absolute_path)
        if from_default:
            result = await self.create_worktree(name)
            return Path(result.absolute_path)
        raise RuntimeError("Invalid create_worktree request: no source and from_default=False")

    async def remove_worktree_by_name(self, name: str, *, force: bool = False) -> None:
        listing = await self.list_worktrees()
        target = None
        for wt in listing.worktrees:
            if wt.name == name:
                target = wt.wtid
                break
        if target is None:
            raise RuntimeError(f"Worktree '{name}' not found")
        await self.delete_worktree(target)

