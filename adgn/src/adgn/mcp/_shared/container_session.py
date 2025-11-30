from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Any, cast

import aiodocker
from fastmcp.server import FastMCP
from fastmcp.server.context import Context

from adgn.mcp._shared.constants import EXIT_CODE_SIGTERM, SLEEP_FOREVER_CMD, WORKING_DIR
from adgn.mcp._shared.types import ContainerImageHistoryEntry, ContainerImageInfo, ContainerInfo
from adgn.mcp.exec.models import MAX_BYTES_CAP, BaseExecResult, ExecInput, async_timer, render_raw_to_result
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

# Exit code returned by SIGTERM; standardized for host-side timeouts

# ---- Container session state ----


@dataclass
class ContainerSessionState:
    docker_client: aiodocker.Docker
    container: dict[str, Any] | None
    image: str
    # Raw volumes argument used to start the container (dict/list or None)
    volumes: dict[str, dict[str, str]] | list[str] | None
    # Container working directory
    working_dir: Path
    # Network mode used to start the container (str: "none", "bridge", "host", or custom network name)
    network_mode: str
    # Environment variables for the container
    environment: dict[str, str] | None
    ephemeral: bool


# ---- Docker helpers ----


async def _init_docker() -> aiodocker.Docker:
    return aiodocker.Docker()


def _shell_join(cmd: Iterable[str]) -> str:
    return shlex.join(list(cmd))


@dataclass
class ContainerOptions:
    image: str
    working_dir: Path = WORKING_DIR
    volumes: dict[str, dict[str, str]] | list[str] | None = None
    network_mode: str = "none"
    environment: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    describe: bool = True
    ephemeral: bool = False

    def to_container_config(
        self,
        *,
        cmd: list[str],
        working_dir: Path | None = None,
        env: dict[str, str] | None = None,
        auto_remove: bool = False,
    ) -> dict[str, Any]:
        """Build Docker container config dict.

        Args:
            cmd: Command to run (list of strings)
            working_dir: Override container working directory (uses self.working_dir if None)
            env: Override environment variables (uses self.environment if None)
            auto_remove: Whether to auto-remove container after exit

        Returns:
            Docker container config dict ready for containers.create()
        """
        return {
            "Image": self.image,
            "Cmd": cmd,
            "WorkingDir": str(working_dir if working_dir is not None else self.working_dir),
            "Env": [f"{k}={v}" for k, v in (env or self.environment or {}).items()],
            "Labels": self.labels or {},
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "HostConfig": _build_host_config(self, auto_remove=auto_remove),
        }


def _session_state_from_ctx(ctx: Any) -> ContainerSessionState:
    return cast(ContainerSessionState, ctx.request_context.lifespan_context)


def _build_host_config(opts: ContainerOptions, *, auto_remove: bool = False) -> dict[str, Any]:
    """Build Docker HostConfig from ContainerOptions.

    Args:
        opts: Container options with volumes and network_mode
        auto_remove: Whether to set AutoRemove (for per-session containers)

    Returns:
        Docker HostConfig dict with Binds and NetworkMode if applicable
    """
    host_config: dict[str, Any] = {}

    if auto_remove:
        host_config["AutoRemove"] = True

    # Convert volumes to binds format
    if opts.volumes and isinstance(opts.volumes, dict):
        binds = []
        for host_path, volume_config in opts.volumes.items():
            bind = f"{host_path}:{volume_config['bind']}"
            if mode := volume_config.get("mode"):
                bind += f":{mode}"
            binds.append(bind)
        if binds:
            host_config["Binds"] = binds

    # Apply network mode if not 'none'
    if opts.network_mode != "none":
        host_config["NetworkMode"] = opts.network_mode

    return host_config


async def _start_container(*, client: aiodocker.Docker, opts: ContainerOptions) -> dict[str, Any]:
    container_config = opts.to_container_config(cmd=SLEEP_FOREVER_CMD, auto_remove=True)

    container = await client.containers.create(container_config)
    await container.start()
    # Return dict format to match expected API; aiodocker containers use _id internally
    return {"Id": container._id, "Name": ""}


# ---- Lifespan factory (per-session container) ----


def make_container_lifespan(opts: ContainerOptions):
    @asynccontextmanager
    async def lifespan(server: FastMCP):  # yields ContainerSessionState
        client = await _init_docker()
        container_dict = None
        try:
            if not opts.ephemeral:
                container_dict = await _start_container(client=client, opts=opts)
            yield ContainerSessionState(
                docker_client=client,
                container=container_dict,
                image=opts.image,
                volumes=opts.volumes,
                working_dir=opts.working_dir,
                network_mode=opts.network_mode,
                environment=opts.environment,
                ephemeral=opts.ephemeral,
            )
        finally:
            if container_dict is not None:
                try:
                    # Get container instance for cleanup
                    container = await client.containers.get(container_dict["Id"])
                    await container.kill()
                    await container.delete(force=True)
                except Exception:
                    # Already removed or cleanup failed
                    pass
            await client.close()

    return lifespan


# Module-level ExecInput to avoid ForwardRef issues during FastMCP signature introspection


# ---- Helpers (small, focused) ----------------------------------------------


def _render_container_result(
    stdout_buf: bytearray, stderr_buf: bytearray, exit_code: int | None, timed_out: bool, duration_ms: int
) -> BaseExecResult:
    """Render container execution output to BaseExecResult."""
    return render_raw_to_result(
        stdout=stdout_buf,
        stderr=stderr_buf,
        exit_code=exit_code,
        timed_out=timed_out,
        max_bytes=MAX_BYTES_CAP,
        duration_ms=duration_ms,
    )


async def _run_ephemeral_container(
    s: ContainerSessionState, prepared_cmd: list[str] | str, input: ExecInput
) -> tuple[bytearray, bytearray, int | None, bool]:
    """Run command in ephemeral container using aiodocker."""
    docker_client = s.docker_client

    # Build ephemeral container options from session state
    ephemeral_opts = ContainerOptions(
        image=s.image,
        working_dir=s.working_dir,
        volumes=s.volumes,
        network_mode=s.network_mode,
        environment=s.environment,
        ephemeral=True,
    )

    ephemeral_config = ephemeral_opts.to_container_config(
        cmd=prepared_cmd if isinstance(prepared_cmd, list) else ["sh", "-c", prepared_cmd],
        working_dir=input.cwd,  # Override if specified
        env=input.env,  # Override if specified
        auto_remove=False,
    )

    # Create and start container
    container = await docker_client.containers.create(ephemeral_config)
    await container.start()

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    timed_out = False
    exit_code: int | None = None

    # Wait for container to finish or timeout using external timeout mechanism
    async def wait_for_completion():
        while True:
            try:
                await container.show()  # Refresh container state
                if container._container["State"]["Status"] not in ("created", "running"):
                    break
            except Exception:
                break
            await asyncio.sleep(0.05)

    timeout_task = asyncio.create_task(asyncio.sleep(input.timeout_ms / 1000.0))
    wait_task = asyncio.create_task(wait_for_completion())

    done, pending = await asyncio.wait({timeout_task, wait_task}, return_when=asyncio.FIRST_COMPLETED)

    # Cancel pending tasks
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    if timeout_task in done:
        # External timeout - we control this
        timed_out = True
        try:
            await container.kill()
            await asyncio.sleep(0.2)
            await container.kill()
        except Exception:
            pass

    if not timed_out:
        try:
            wait_result = await container.wait()
            exit_code = wait_result.get("StatusCode")
        except Exception:
            exit_code = EXIT_CODE_SIGTERM
    # Note: Don't set exit_code when timed_out is True - let render_raw_to_result handle it

    # Get logs with proper stream separation
    try:
        stdout_logs = await container.log(stdout=True, stderr=False)
        stderr_logs = await container.log(stdout=False, stderr=True)

        def extend_buf_from_logs(buf: bytearray, logs):
            """Helper to process log data into buffer."""
            if isinstance(logs, list):
                for chunk in logs:
                    if isinstance(chunk, bytes):
                        buf.extend(chunk)
                    elif isinstance(chunk, str):
                        buf.extend(chunk.encode())
            elif isinstance(logs, bytes):
                buf.extend(logs)
            elif isinstance(logs, str):
                buf.extend(logs.encode())

        extend_buf_from_logs(stdout_buf, stdout_logs)
        extend_buf_from_logs(stderr_buf, stderr_logs)
    except Exception:
        pass

    # Remove container
    with suppress(Exception):
        await container.delete(force=True)

    return stdout_buf, stderr_buf, exit_code, timed_out


async def _run_session_container(
    s: ContainerSessionState, prepared_cmd: list[str] | str, input: ExecInput, opts: ContainerOptions
) -> tuple[bytearray, bytearray, int | None, bool]:
    """Run command in per-session container using aiodocker exec."""
    container = s.container
    if container is None:
        raise RuntimeError("No per-session container available")

    docker_client = s.docker_client
    container_instance = await docker_client.containers.get(container["Id"])

    # Prepare command
    cmd = prepared_cmd if isinstance(prepared_cmd, list) else ["sh", "-c", prepared_cmd]

    # Execute with timeout handling
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    timed_out = False
    exit_code = None

    # Create exec instance with explicit args (avoid **kwargs issues)
    exec_obj = await container_instance.exec(
        cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=False,  # No TTY to ensure stdout/stderr separation
        workdir=str(input.cwd) if input.cwd is not None else str(s.working_dir),
        environment=input.env,
        user=input.user or "",
    )

    # Start exec and collect output with timeout
    stream: Any = exec_obj.start()

    async def collect_output():
        while True:
            chunk = await stream.read_out()
            if chunk is None:
                break

            # chunk is a Message namedtuple with stream (1=stdout, 2=stderr) and data (bytes)
            chunk_bytes = chunk.data  # Always bytes from aiodocker

            # Check stream type (1=stdout, 2=stderr)
            stream_type = chunk.stream
            if stream_type == 1:
                stdout_buf.extend(chunk_bytes)
            elif stream_type == 2:
                stderr_buf.extend(chunk_bytes)
            else:
                # Unknown stream type, default to stdout
                stdout_buf.extend(chunk_bytes)

    # Implement external timeout mechanism
    timeout_task = asyncio.create_task(asyncio.sleep(input.timeout_ms / 1000.0))
    collect_task = asyncio.create_task(collect_output())

    done, pending = await asyncio.wait({timeout_task, collect_task}, return_when=asyncio.FIRST_COMPLETED)

    # Cancel pending tasks
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    if timeout_task in done:
        # External timeout - kill and restart container
        timed_out = True
        exit_code = None
        await container_instance.kill()
        await asyncio.sleep(0.5)
        s.container = await _start_container(client=docker_client, opts=opts)
    else:
        # Command completed normally - inspect exec for exit code
        inspect_result = await exec_obj.inspect()
        exit_code = inspect_result.get("ExitCode", 0)

    return stdout_buf, stderr_buf, exit_code, timed_out


# ---- Register exec tool and resources on a FastMCP server -------------------


def register_container(mcp: NotifyingFastMCP, opts: ContainerOptions, *, tool_name: str = "exec") -> None:
    """Register both container.info resource and exec tool on a FastMCP server.

    This folds resource and tool registration into a single call to avoid double registration.
    """

    # Resource: single JSON describing container/session
    async def container_info_json(ctx: Context) -> dict[str, Any]:
        s = _session_state_from_ctx(ctx)
        img_info = await s.docker_client.images.inspect(s.image)
        img_history_raw = await s.docker_client.images.history(s.image)
        img_history = (
            [ContainerImageHistoryEntry.model_validate(entry) for entry in img_history_raw] if img_history_raw else None
        )

        ci = ContainerInfo(
            image=ContainerImageInfo(
                name=s.image, id=img_info.get("Id", "unknown"), tags=img_info.get("RepoTags", [s.image])
            ),
            container_id=(s.container["Id"] if s.container is not None else None),
            volumes=s.volumes,
            working_dir=str(s.working_dir),
            network_mode=s.network_mode,
            image_history=img_history,
            ephemeral=s.ephemeral,
        )
        return ci.model_dump(mode="json")

    # Ensure the context annotation is preserved after future-annotations rewriting so
    # FastMCP treats this as a static resource rather than a template.
    container_info_json.__annotations__["ctx"] = Context
    mcp.resource(
        "resource://container.info",
        mime_type="application/json",
        name="container.info",
        title="Container session metadata",
        description="Docker container details for this session",
    )(container_info_json)

    @mcp.tool(name=tool_name, flat=True)
    async def tool_exec(input: ExecInput, ctx: Context) -> BaseExecResult:
        """Run a shell command inside the per-session Docker container."""
        async with async_timer() as get_duration_ms:
            s = _session_state_from_ctx(ctx)

            # Build command; for non-shell, run under sh -lc
            prepared_cmd: list[str] | str
            prepared_cmd = _shell_join(input.cmd) if input.shell else ["sh", "-lc", _shell_join(input.cmd)]

            if s.ephemeral or opts.ephemeral:
                stdout_buf, stderr_buf, exit_code, timed_out = await _run_ephemeral_container(s, prepared_cmd, input)
            else:
                stdout_buf, stderr_buf, exit_code, timed_out = await _run_session_container(
                    s, prepared_cmd, input, opts
                )

            duration_ms = get_duration_ms()
            return _render_container_result(stdout_buf, stderr_buf, exit_code, timed_out, duration_ms)
