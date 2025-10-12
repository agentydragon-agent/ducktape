from __future__ import annotations

from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import math
from pathlib import Path
import shlex
import signal
import threading
import time
from typing import Any, cast

from fastmcp.server import FastMCP
from fastmcp.server.context import Context

from adgn.mcp._shared.constants import (
    EXIT_CODE_SIGTERM,
    SLEEP_FOREVER_CMD,
)
from adgn.mcp._shared.types import (
    ContainerImageInfo,
    ContainerInfo,
    ExecInput,
    ExecResult,
    NetworkMode,
)
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
import docker
from docker import DockerClient
from docker.models.containers import Container

# Exit code returned by SIGTERM; standardized for host-side timeouts

# ---- Container session state ----


@dataclass
class ContainerSessionState:
    docker_client: DockerClient
    container: Container | None
    image: str
    # Raw volumes argument used to start the container (dict/list or None)
    volumes: dict[str, dict[str, str]] | list[str] | None
    # Container working directory
    working_dir: Path
    # Network mode used to start the container
    network_mode: NetworkMode
    ephemeral: bool


# ---- Docker helpers ----


def _init_docker() -> DockerClient:
    return docker.from_env()


def _shell_join(cmd: Iterable[str]) -> str:
    return shlex.join(list(cmd))


def _get_low_level_api(container: Container) -> docker.APIClient:
    """Return the low-level Docker API client for a container.

    Enforces that containers in this system come from a high-level
    DockerClient; if not, supports direct APIClient as a fallback.
    """
    client = container.client
    if isinstance(client, DockerClient):
        return client.api
    if isinstance(client, docker.APIClient):  # pragma: no cover (fallback path)
        return client
    raise TypeError(f"Unsupported container.client type: {type(client)!r}")


@dataclass
class ContainerOptions:
    image: str
    working_dir: Path = Path("/workspace")
    volumes: dict[str, dict[str, str]] | list[str] | None = None
    network_mode: NetworkMode = NetworkMode.NONE
    environment: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    describe: bool = True
    ephemeral: bool = False


def _session_state_from_ctx(ctx: Any) -> ContainerSessionState:
    return cast(ContainerSessionState, ctx.request_context.lifespan_context)


def _start_container(*, client: DockerClient, opts: ContainerOptions) -> Container:
    return client.containers.run(
        image=opts.image,
        command=SLEEP_FOREVER_CMD,
        detach=True,
        tty=False,
        working_dir=str(opts.working_dir),
        network_mode=str(opts.network_mode),
        volumes=opts.volumes,
        environment=opts.environment,
        labels=opts.labels,
        # Run as image default user (root by default). No override.
        auto_remove=True,
    )


# ---- Lifespan factory (per-session container) ----


def make_container_lifespan(opts: ContainerOptions):
    @asynccontextmanager
    async def lifespan(server: FastMCP):  # yields ContainerSessionState
        client = _init_docker()
        container: Container | None = None
        if not opts.ephemeral:
            container = _start_container(client=client, opts=opts)
        try:
            yield ContainerSessionState(
                docker_client=client,
                container=container,
                image=opts.image,
                volumes=opts.volumes,
                working_dir=opts.working_dir,
                network_mode=opts.network_mode,
                ephemeral=opts.ephemeral,
            )
        finally:
            if container is not None:
                try:
                    container.stop(timeout=1)
                except docker.errors.NotFound:
                    # Already removed
                    pass
                except docker.errors.APIError:
                    # Cleanup failure: surface as API error
                    raise

    return lifespan


# Module-level ExecInput to avoid ForwardRef issues during FastMCP signature introspection


# ---- Helpers (small, focused) ----------------------------------------------


def _deadline_from_ms(ms: int) -> float:
    return time.monotonic() + max(1, int(math.ceil(ms / 1000)))


def _demux_extend(stdout_buf: bytearray, stderr_buf: bytearray, chunk: Any) -> None:
    if isinstance(chunk, tuple):
        out_b, err_b = chunk
        if out_b:
            stdout_buf.extend(out_b)
        if err_b:
            stderr_buf.extend(err_b)
    else:
        if chunk:
            stdout_buf.extend(chunk)


def _collect_logs(container: Container) -> tuple[bytes, bytes]:
    # Do not swallow log collection failures; these indicate a serious issue.
    return (
        container.logs(stdout=True, stderr=False),
        container.logs(stdout=False, stderr=True),
    )


# ---- Register exec tool and resources on a FastMCP server -------------------


def register_container(
    mcp: NotifyingFastMCP, opts: ContainerOptions, *, tool_name: str = "exec"
) -> None:
    """Register both container.info resource and exec tool on a FastMCP server.

    This folds resource and tool registration into a single call to avoid double registration.
    """

    # Resource: single JSON describing container/session
    def container_info_json(ctx: Context) -> dict[str, Any]:
        s = _session_state_from_ctx(ctx)
        img = s.docker_client.images.get(s.image)
        ci = ContainerInfo(
            image=ContainerImageInfo(name=s.image, id=img.id, tags=img.tags),
            container_id=(s.container.id if s.container is not None else None),
            volumes=s.volumes,
            working_dir=str(s.working_dir),
            network_mode=NetworkMode(s.network_mode.value),
            image_history=cast(Any, s.docker_client).api.history(img.id),
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

    # Tool: container exec (flat MCP payload, validated via ExecInput)
    @mcp.tool(name=tool_name, flat=True, flat_output_model=ExecResult)
    def tool_exec(input: ExecInput, ctx: Context) -> ExecResult:
        """Run a shell command inside the per-session Docker container."""
        s = _session_state_from_ctx(ctx)

        # Build command; for non-shell, run under sh -lc
        prepared_cmd: list[str] | str
        if input.shell:
            prepared_cmd = _shell_join(input.cmd)
        else:
            prepared_cmd = ["sh", "-lc", _shell_join(input.cmd)]

        if s.ephemeral or opts.ephemeral:
            # Ephemeral per-call container
            container = s.docker_client.containers.run(
                image=s.image,
                command=prepared_cmd,
                detach=True,
                tty=input.tty,
                working_dir=str(input.cwd) if input.cwd is not None else str(s.working_dir),
                network_mode=str(s.network_mode),
                volumes=s.volumes,
                environment=input.env,
                labels=None,
                auto_remove=False,
            )
            stdout_buf = bytearray()
            stderr_buf = bytearray()
            timed_out = False
            exit_code: int | None = None
            deadline = _deadline_from_ms(input.timeout_ms)
            while True:
                container.reload()
                if container.status not in ("created", "running"):
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    try:
                        container.kill(signal=signal.SIGTERM)
                        time.sleep(0.2)
                        container.kill(signal=signal.SIGKILL)
                    except docker.errors.APIError:
                        pass
                    break
                time.sleep(0.05)
            if not timed_out:
                info = container.wait()
                exit_code = cast(int | None, info.get("StatusCode"))
            else:
                # Standardize timeout exit code to SIGTERM
                exit_code = EXIT_CODE_SIGTERM
            out_b, err_b = _collect_logs(container)
            if out_b:
                stdout_buf.extend(out_b)
            if err_b:
                stderr_buf.extend(err_b)
            try:
                container.remove(force=True)
            except docker.errors.APIError:
                pass
            return ExecResult(
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=stdout_buf.decode(errors="replace"),
                stderr=stderr_buf.decode(errors="replace"),
            )

        # Per-session container exec
        c = s.container
        if c is None:
            raise RuntimeError("No per-session container available")
        api: docker.APIClient = _get_low_level_api(c)
        extra: dict[str, Any] = {}
        if input.user is not None:
            extra["user"] = input.user
        cwd_str = str(input.cwd) if input.cwd is not None else str(s.working_dir)
        cid = c.id
        if not isinstance(cid, str) or not cid:
            raise RuntimeError("container has no id for exec")
        exec_id = api.exec_create(
            container=cid,
            cmd=prepared_cmd,
            stdout=True,
            stderr=True,
            stdin=False,
            tty=input.tty,
            workdir=cwd_str,
            environment=input.env,
            **extra,
        )["Id"]

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        timed_out = False
        exit_code = None
        stop_evt = threading.Event()

        def _killer():
            nonlocal timed_out
            if not stop_evt.wait(timeout=max(1, int(math.ceil(input.timeout_ms / 1000)))):
                timed_out = True
                try:
                    if s.container is not None:
                        s.container.kill(signal=signal.SIGTERM)
                        time.sleep(0.5)
                        s.container.kill(signal=signal.SIGKILL)
                except docker.errors.APIError:
                    pass

        thr = threading.Thread(target=_killer, daemon=True)
        thr.start()
        for chunk in api.exec_start(exec_id, stream=True, demux=True):
            _demux_extend(stdout_buf, stderr_buf, chunk)
        stop_evt.set()
        thr.join(timeout=0.1)
        if not timed_out:
            inspect_info = api.exec_inspect(exec_id)
            exit_code = inspect_info.get("ExitCode")
            if exit_code == EXIT_CODE_SIGTERM:
                timed_out = True
                # Standardize timeout exit code to SIGTERM
                exit_code = EXIT_CODE_SIGTERM
        else:
            try:
                c.kill(signal=signal.SIGKILL)
            except docker.errors.APIError:
                pass
            s.container = _start_container(client=s.docker_client, opts=opts)
            # Standardize timeout exit code to SIGTERM
            exit_code = EXIT_CODE_SIGTERM
        return ExecResult(
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_buf.decode(errors="replace"),
            stderr=stderr_buf.decode(errors="replace"),
        )
