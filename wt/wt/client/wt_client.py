"""wt daemon client for fast working directory status.

This client connects to the wt multiplexing daemon via socket,
providing both low-level daemon communication and high-level status operations.
"""

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar, cast

import click
import psutil
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..shared.configuration import Configuration
from ..shared.error_handling import validate_worktree_name
from ..shared.protocol import (
    ErrorCodes,
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

T = TypeVar("T")


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: object | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass
class WtClient:
    """JSON-RPC client for communicating with the worktree management daemon."""

    config: Configuration
    verbose: bool = False
    _handshake_pipe: int | None = field(default=None, init=False)
    _progress_callback: Callable[[ProgressEvent], None] | None = field(
        default=None,
        init=False,
    )
    _hook_output_callback: Callable[[HookOutputEvent], None] | None = field(
        default=None,
        init=False,
    )

    # Class-level lock to prevent multiple daemon startups
    _daemon_start_lock = asyncio.Lock()

    def __post_init__(self) -> None:
        # Ensure daemon directory exists
        self.config.wt_dir.mkdir(exist_ok=True)

    def set_progress_callback(self, cb: Callable[[ProgressEvent], None] | None) -> None:
        self._progress_callback = cb

    def set_hook_output_callback(
        self,
        cb: Callable[[HookOutputEvent], None] | None,
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

            # Use handshake pipe to get immediate readiness without busy-wait
            await self._start_daemon_background()

            try:
                loop = asyncio.get_event_loop()
                reader_future = loop.run_in_executor(
                    None,
                    self._read_handshake_from_pipe,
                )
                handshake_data = await asyncio.wait_for(
                    asyncio.shield(reader_future),
                    timeout=self.config.startup_timeout.total_seconds(),
                )

                protocol_version = handshake_data.get("protocol_version", 0)
                if protocol_version != 1:
                    raise RuntimeError(
                        f"Incompatible daemon protocol version {protocol_version}, expected 1",
                    )

                if handshake_data.get("success"):
                    logger.info("Daemon startup handshake ok")
                    return
                error_message = handshake_data.get("error", "Unknown startup error")
                raise RuntimeError(f"Daemon startup failed:\n{error_message}")

            except asyncio.TimeoutError:
                timeout_secs = self.config.startup_timeout.total_seconds()
                raise RuntimeError(
                    f"Daemon startup timed out after {timeout_secs:.1f} seconds",
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
                        f"pid file exists: {self.config.daemon_pid_path.exists()}",
                    )
                    if self.config.daemon_pid_path.exists():
                        diag.append(
                            f"pid file contents: {self.config.daemon_pid_path.read_text().strip()}",
                        )
                    diag.append(
                        f"socket exists: {self.config.daemon_socket_path.exists()}",
                    )
                except OSError:
                    pass
                raise RuntimeError("Daemon startup failed.\n" + "\n".join(diag)) from e
            finally:
                self._handshake_pipe = None

    async def _start_daemon_background(self) -> None:
        """Start daemon in background with a dedicated handshake pipe (no double-fork).

        Implementation: create a pipe, launch wt.server.wt_server via subprocess.Popen,
        pass the write-end FD using pass_fds and WT_HANDSHAKE_FD so the daemon can emit
        JSON StartupMessage lines. Keep the read-end in this process for synchronous readiness.
        """
        # Create pipe for handshake communication (dedicated FD)
        read_fd, write_fd = os.pipe()
        with contextlib.suppress(Exception):
            os.set_inheritable(write_fd, True)

        env = os.environ.copy()
        env["WT_HANDSHAKE_FD"] = str(write_fd)
        # Ensure PYTHONPATH contains project root so -m import works when running from tests
        try:
            project_root = str(Path(__file__).resolve().parents[2])
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{project_root}:{existing}" if existing else project_root
            )
        except Exception:
            pass

        # Launch daemon as a new session; do not inherit stdio; only the handshake FD is kept
        try:
            subprocess.Popen(  # noqa: ASYNC220
                [sys.executable, "-m", "wt.server.wt_server"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(write_fd,),
                close_fds=True,
            )
        finally:
            # Parent keeps only the read end; close write end in parent
            with contextlib.suppress(Exception):
                os.close(write_fd)

        # Store read pipe so _read_handshake_from_pipe can consume it
        self._handshake_pipe = read_fd

    def _read_handshake_from_pipe(self) -> dict[str, object]:
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
                    click.echo(f"[daemon-handshake] {line.rstrip()}")
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = StartupMessage.model_validate_json(line)
                except ValidationError:
                    continue
                last_obj = cast(dict[str, object], obj.model_dump())
                if not obj.success:
                    return last_obj
                if obj.ready:
                    return last_obj

    async def get_status(
        self,
        worktree_ids: list[WorktreeID] | None = None,
    ) -> StatusResponse:
        await self._start_daemon_if_needed()
        ids: list[WorktreeID] = (
            cast(list[WorktreeID], worktree_ids) if worktree_ids is not None else []
        )
        params = StatusParams(worktree_ids=ids)
        return await self._rpc("get_status", params, TypeAdapter(StatusResponse))

    async def get_working_directory_status(
        self,
        worktree_path: Path,
    ) -> tuple[list[str], list[str]]:
        """Get working directory status for a single worktree via daemon response flags."""
        # Use server-side identification to safely convert path to WorktreeID
        try:
            identify_result = await self.identify_worktree(str(worktree_path))
            if identify_result.wtid is None:
                return [], []
            status_response = await self.get_status([identify_result.wtid])
        except RpcError as e:
            # Only special-case unmanaged worktrees by code; otherwise bubble up
            if e.code == ErrorCodes.WORKTREE_NOT_FOUND:
                return [], []
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
            hook_cb = self._hook_output_callback  # type: ignore[assignment]
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
                    hook_ev: HookOutputEvent = HookOutputEvent.model_validate(obj)
                    if callable(hook_cb):
                        hook_cb(hook_ev)
                    if hook_ev.stream.value == "stdout":
                        hook_stdout.append(hook_ev.data)
                    else:
                        hook_stderr.append(hook_ev.data)
                    continue
                if ev == "progress":
                    prog_ev: ProgressEvent = ProgressEvent.model_validate(obj)
                    if callable(progress_cb):
                        progress_cb(prog_ev)
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
                if post := result.post_hook:

                    def _echo_io() -> None:
                        out = "\n".join(s for s in [post.stdout, post.stderr] if s)
                        if out.strip():
                            click.echo(out)

                    # Non-zero exit code => fail
                    if (ec := post.exit_code) not in (None, 0):
                        _echo_io()
                        raise RuntimeError(
                            f"Post-creation script failed with exit code {ec}",
                        )
                    # Execution error surfaced by server (e.g. script disappeared)
                    if err := post.error:
                        _echo_io()
                        if err == "timeout":
                            if (ts := post.timeout_secs) is not None:
                                raise RuntimeError(
                                    f"Post-creation script timed out after {ts:.1f}s",
                                )
                            raise RuntimeError("Post-creation script timed out")
                        raise RuntimeError(
                            f"Post-creation script error: {err}",
                        )
                    # Ran flag false (e.g. not_found/not_file in legacy path) => fail
                    if not post.ran:
                        _echo_io()
                        raise RuntimeError("Post-creation script did not run")
                return result
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as e:
                logger.exception("Failed to parse daemon worktree_create response")
                raise RuntimeError(
                    f"Failed to parse daemon worktree_create response: {e}",
                )

        except (ConnectionError, FileNotFoundError, OSError, asyncio.TimeoutError) as e:
            if self.verbose:
                logger.exception(
                    "Failed to communicate with daemon for worktree_create",
                )
            raise RuntimeError(f"Daemon worktree_create communication failed: {e}")

    async def delete_worktree(
        self,
        wtid: WorktreeID,
        *,
        force: bool = False,
    ) -> WorktreeDeleteResult:
        await self._start_daemon_if_needed()
        return await self._rpc(
            "worktree_delete",
            WorktreeDeleteParams(wtid=wtid, force=force),
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

    async def _rpc(
        self,
        method: str,
        params_model: BaseModel | dict[str, object],
        result_adapter: TypeAdapter[T],
    ) -> T:
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
                self.config.daemon_socket_path,
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
                raise RpcError(err.error.code, err.error.message, err.id)
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
            if isinstance(e, RpcError):
                raise RuntimeError(f"RPC {method} failed ({e.code}): {e}")
            raise RuntimeError(f"RPC {method} failed: {e}")

    async def resolve_path(self, params: WorktreeResolvePathParams) -> str:
        result: WorktreeResolvePathResult = await self._rpc(
            "worktree_resolve_path",
            params,
            TypeAdapter(WorktreeResolvePathResult),
        )
        return result.absolute_path

    async def resolve_path_simple(
        self,
        worktree_name: str | None,
        path_spec: str,
    ) -> Path:
        params = WorktreeResolvePathParams(
            worktree_name=worktree_name,
            path_spec=path_spec,
            current_path=str(Path.cwd()),
        )
        return Path(await self.resolve_path(params))

    async def teleport_target(
        self,
        target_name: str,
        current_path: str,
    ) -> TeleportCdThere | TeleportDoesNotExist:
        return await self._rpc(
            "worktree_teleport_target",
            WorktreeTeleportTargetParams(
                target_name=target_name,
                current_path=current_path,
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
            "Invalid create_worktree request: no source and from_default=False",
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
        await self.delete_worktree(target, force=force)
