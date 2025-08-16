"""wt daemon client for fast working directory status.

This client connects to the wt multiplexing daemon via socket,
providing both low-level daemon communication and high-level status operations.
"""

import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import psutil
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..shared.configuration import Configuration
from ..shared.error_handling import validate_worktree_name
from ..shared.protocol import (
    ErrorResponse,
    HookOutputEvent,
    ProgressEvent,
    Request,
    Response,
    StartupMessage,
    StatusParams,
    StatusResponse,
    TeleportCdThere,
    TeleportDoesNotExist,
    TeleportResult,
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

logger = logging.getLogger(__name__)


@dataclass
class WtClient:
    """JSON-RPC client for communicating with the worktree management daemon."""

    config: Configuration
    verbose: bool = False
    _handshake_pipe: int | None = field(default=None, init=False)
    _progress_callback: Callable[[ProgressEvent], None] | None = field(
        default=None, init=False
    )
    _hook_output_callback: Callable[[HookOutputEvent], None] | None = field(
        default=None, init=False
    )

    # Class-level lock to prevent multiple daemon startups
    _daemon_start_lock = asyncio.Lock()

    def __post_init__(self) -> None:
        # Ensure daemon directory exists
        self.config.wt_dir.mkdir(exist_ok=True)

    def set_progress_callback(self, cb: Callable[[ProgressEvent], None] | None) -> None:
        self._progress_callback = cb

    def set_hook_output_callback(
        self, cb: Callable[[HookOutputEvent], None] | None
    ) -> None:
        self._hook_output_callback = cb

    async def current_worktree_info(self) -> tuple[Path | None, str | None]:
        res = await self.identify_worktree(str(Path.cwd()))
        if not res.is_worktree or not res.name:
            return None, None
        by_name = await self.get_worktree_by_name(res.name)
        if by_name.exists and by_name.absolute_path:
            return Path(by_name.absolute_path), (res.relative_path or None)
        return None, None

    def _is_daemon_running(self) -> bool:
        """Check if the daemon is running."""
        try:
            if not self.config.daemon_pid_path.exists():
                return False

            pid_str = self.config.daemon_pid_path.read_text().strip()
            if not pid_str:
                return False

            pid = int(pid_str)

            # Check if process exists and socket is accessible
            return bool(
                psutil.pid_exists(pid) and self.config.daemon_socket_path.exists(),
            )

        except (ValueError, OSError):
            return False

    async def _start_daemon_if_needed(self) -> None:
        """Start daemon if not running."""

        async with self._daemon_start_lock:
            if self._is_daemon_running():
                logger.debug("Daemon already running for %s", self.config.main_repo)
                return

            logger.info("Starting wt daemon for %s", self.config.main_repo)
            logger.debug("Daemon socket: %s", self.config.daemon_socket_path)
            logger.debug("Daemon logs: %s", self.config.wt_dir / "daemon.log")
            logger.info("wt: starting daemon … (%s)", self.config.daemon_socket_path)

            # Use original double-fork + handshake pipe approach to start the daemon
            await self._start_daemon_background()

            try:
                loop = asyncio.get_event_loop()
                reader_future = loop.run_in_executor(
                    None, self._read_handshake_from_pipe
                )
                first_wait = min(1.0, self.config.startup_timeout.total_seconds())
                try:
                    handshake_data = await asyncio.wait_for(
                        asyncio.shield(reader_future), timeout=first_wait
                    )
                except asyncio.TimeoutError:
                    remaining = max(
                        0.0, self.config.startup_timeout.total_seconds() - first_wait
                    )
                    handshake_data = await asyncio.wait_for(
                        asyncio.shield(reader_future),
                        timeout=remaining if remaining > 0 else 0.1,
                    )

                protocol_version = handshake_data.get("protocol_version", 0)
                if protocol_version != 1:
                    raise RuntimeError(
                        f"Incompatible daemon protocol version {protocol_version}, expected 1"
                    )

                if handshake_data.get("success"):
                    pid = handshake_data.get("pid")
                    logger.info("wt daemon: startup handshake ok (pid %s)", pid)
                    if self._is_daemon_running():
                        logger.info(
                            "Daemon started successfully with handshake confirmation"
                        )
                        return
                    raise RuntimeError(
                        "Daemon handshake successful but daemon not accessible"
                    )
                error_message = handshake_data.get("error", "Unknown startup error")
                raise RuntimeError(f"Daemon startup failed:\n{error_message}")

            except asyncio.TimeoutError:
                timeout_secs = self.config.startup_timeout.total_seconds()
                logger.warning(
                    "Daemon startup timed out - no handshake received within %.1f seconds",
                    timeout_secs,
                )
                raise RuntimeError(
                    f"Daemon startup timed out after {timeout_secs:.1f} seconds"
                )
            except (OSError, RuntimeError, ValueError) as e:
                diag = []
                try:
                    daemon_log = self.config.wt_dir / "daemon.log"
                    diag.append(f"daemon.log: {daemon_log}")
                    if daemon_log.exists():
                        tail = daemon_log.read_text(errors="ignore").splitlines()[-50:]
                        diag.append("daemon.log (tail):\n" + "\n".join(tail))
                except OSError:
                    pass
                try:
                    diag.append(
                        f"pid file exists: {self.config.daemon_pid_path.exists()}"
                    )
                    if self.config.daemon_pid_path.exists():
                        diag.append(
                            f"pid file contents: {self.config.daemon_pid_path.read_text().strip()}"
                        )
                    diag.append(
                        f"socket exists: {self.config.daemon_socket_path.exists()}"
                    )
                except OSError:
                    pass
                raise RuntimeError("Daemon startup failed.\n" + "\n".join(diag)) from e
            finally:
                self._handshake_pipe = None

    async def _start_daemon_background(self) -> None:
        """Start daemon in background using proper double-fork daemonization."""

        # Create pipe for handshake communication (dedicated FD, not stdout)
        handshake_read, handshake_write = os.pipe()
        with contextlib.suppress(Exception):
            os.set_inheritable(handshake_write, True)

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
                        log_file = self.config.wt_dir / "daemon.log"
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
                            project_root = str(Path(__file__).resolve().parents[2])
                            existing = env.get("PYTHONPATH", "")
                            env["PYTHONPATH"] = (
                                f"{project_root}:{existing}"
                                if existing
                                else project_root
                            )
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

        if not self._handshake_pipe:
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
                except ValidationError:
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
        await self._start_daemon_if_needed()
        params = StatusParams(
            worktree_ids=[wtid for wtid in (worktree_ids or []) if wtid is not None]
        )
        return await self._rpc("get_status", params, TypeAdapter(StatusResponse))

    async def get_working_directory_status(
        self,
        worktree_path: Path,
    ) -> tuple[list[str], list[str]]:
        """Get working directory status for a single worktree via daemon response flags."""
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

        if not status_response.items:
            return [], []

        # Extract the single result
        item = next(iter(status_response.items.values()))
        result = item.status

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

        if not self.config.daemon_socket_path.exists():
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
                self.config.daemon_socket_path,
            )

            # Send request
            request_data = request.model_dump_json().encode()
            writer.write(request_data)
            writer.write(b"\n")
            await writer.drain()

            hook_stdout: list[str] = []
            hook_stderr: list[str] = []
            response_json = None

            progress_cb = self._progress_callback
            hook_cb = self._hook_output_callback
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode().strip()
                # Try to parse as JSON object
                obj = json.loads(text)
                # Dispatch on event type if present
                ev = obj.get("event") if isinstance(obj, dict) else None
                if ev == "hook_output":
                    msg = HookOutputEvent.model_validate(obj)
                    if callable(hook_cb):
                        hook_cb(msg)
                    if msg.stream.value == "stdout":
                        hook_stdout.append(msg.data)
                    else:
                        hook_stderr.append(msg.data)
                    continue
                if ev == "progress":
                    msg = ProgressEvent.model_validate(obj)
                    if callable(progress_cb):
                        progress_cb(msg)
                    continue
                # Otherwise treat as final response
                response_json = obj
                break
            if not response_json:
                raise RuntimeError("No response from daemon for worktree_create")

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
                        out = (
                            (result.post_hook.stdout or "")
                            + ("\n" if result.post_hook.stdout else "")
                            + (result.post_hook.stderr or "")
                        )
                        if out.strip():
                            print(out)
                        raise RuntimeError(
                            f"Post-creation script failed with exit code {result.post_hook.exit_code}",
                        )
                    # Execution error surfaced by server (e.g. script disappeared)
                    if result.post_hook.error:
                        out = (
                            (result.post_hook.stdout or "")
                            + ("\n" if result.post_hook.stdout else "")
                            + (result.post_hook.stderr or "")
                        )
                        if out.strip():
                            print(out)
                        raise RuntimeError(
                            f"Post-creation script error: {result.post_hook.error}",
                        )
                    # Ran flag false (e.g. not_found/not_file in legacy path) => fail
                    if not result.post_hook.ran:
                        out = (
                            (result.post_hook.stdout or "")
                            + ("\n" if result.post_hook.stdout else "")
                            + (result.post_hook.stderr or "")
                        )
                        if out.strip():
                            print(out)
                        raise RuntimeError("Post-creation script did not run")
                return result
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as e:
                logger.exception("Failed to parse daemon worktree_create response")
                raise RuntimeError(
                    f"Failed to parse daemon worktree_create response: {e}"
                )

        except (ConnectionError, FileNotFoundError, OSError, asyncio.TimeoutError) as e:
            logger.exception("Failed to communicate with daemon for worktree_create")
            raise RuntimeError(f"Daemon worktree_create communication failed: {e}")

    async def delete_worktree(self, wtid: WorktreeID) -> WorktreeDeleteResult:
        await self._start_daemon_if_needed()
        return await self._rpc(
            "worktree_delete",
            WorktreeDeleteParams(wtid=wtid),
            TypeAdapter(WorktreeDeleteResult),
        )

    async def list_worktrees(self) -> WorktreeListResult:
        await self._start_daemon_if_needed()
        return await self._rpc("worktree_list", {}, TypeAdapter(WorktreeListResult))

    async def identify_worktree(self, absolute_path: str) -> WorktreeIdentifyResult:
        await self._start_daemon_if_needed()
        return await self._rpc(
            "worktree_identify",
            WorktreeIdentifyParams(absolute_path=absolute_path),
            TypeAdapter(WorktreeIdentifyResult),
        )

    async def get_worktree_by_name(self, name: str) -> WorktreeGetByNameResult:
        return await self._rpc(
            "worktree_get_by_name",
            WorktreeGetByNameParams(name=name),
            TypeAdapter(WorktreeGetByNameResult),
        )

    async def _rpc(self, method: str, params_model, result_adapter: TypeAdapter):
        await self._start_daemon_if_needed()
        if not self.config.daemon_socket_path.exists():
            raise RuntimeError("Daemon socket not available")
        if isinstance(params_model, BaseModel):
            params = params_model.model_dump()
        elif isinstance(params_model, dict):
            params = params_model
        else:
            params = {}
        req = Request(method=method, params=params, id=uuid.uuid4())
        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.daemon_socket_path
            )
            writer.write(req.model_dump_json().encode())
            writer.write(b"\n")
            await writer.drain()
            data = await reader.readline()
            text = data.decode().strip()
            writer.close()
            await writer.wait_closed()
            obj = json.loads(text)
            if "error" in obj:
                err = ErrorResponse.model_validate(obj)
                raise RuntimeError(err.error.message)
            resp = Response.model_validate(obj)
            return result_adapter.validate_python(resp.result)
        except (
            ConnectionError,
            FileNotFoundError,
            OSError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            ValidationError,
        ) as e:
            logger.error("RPC %s failed: %s", method, e)
            raise RuntimeError(f"RPC {method} failed: {e}")

    async def resolve_path(self, params: WorktreeResolvePathParams) -> str:
        result = await self._rpc(
            "worktree_resolve_path", params, TypeAdapter(WorktreeResolvePathResult)
        )
        return result.absolute_path

    async def resolve_path_simple(
        self, worktree_name: str | None, path_spec: str
    ) -> Path:
        params = WorktreeResolvePathParams(
            worktree_name=worktree_name,
            path_spec=path_spec,
            current_path=str(Path.cwd()),
        )
        return Path(await self.resolve_path(params))

    async def teleport_target(
        self, target_name: str, current_path: str
    ) -> TeleportCdThere | TeleportDoesNotExist:
        return await self._rpc(
            "worktree_teleport_target",
            WorktreeTeleportTargetParams(
                target_name=target_name, current_path=current_path
            ),
            TypeAdapter(TeleportResult),
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
        if source_name:
            src = await self.get_worktree_by_name(source_name)
            if not src.exists or not src.wtid:
                raise RuntimeError(f"Worktree '{source_name}' not found")
            result = await self.create_worktree(name, source_wtid=src.wtid)
            return Path(result.absolute_path)
        if from_default:
            result = await self.create_worktree(name)
            return Path(result.absolute_path)
        raise RuntimeError(
            "Invalid create_worktree request: no source and from_default=False"
        )

    async def remove_worktree_by_name(self, name: str, *, force: bool = False) -> None:
        listing = await self.list_worktrees()
        target = None
        for wt in listing.worktrees:
            if wt.name == name:
                target = wt.wtid
                break
        if target is None:
            raise RuntimeError(f"Worktree '{name}' not found")
        # Server currently always forces removal; 'force' retained for CLI parity
        await self.delete_worktree(target)
