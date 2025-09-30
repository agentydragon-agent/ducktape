from __future__ import annotations

from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
import shlex
import math
from typing import Any, cast

import docker
from docker.models.containers import Container
from mcp.server.fastmcp import FastMCP
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model

from adgn.mcp._shared.constants import SLEEP_FOREVER_CMD
from adgn.mcp._shared.types import ExecInput, ExecResult

# Exit code returned by `timeout -s TERM` on termination
EXIT_CODE_SIGTERM = 143

# ---- Container session state ----


@dataclass
class ContainerSessionState:
    docker_client: docker.DockerClient
    container: Container
    image: str
    # Raw volumes argument used to start the container (dict/list or None)
    volumes: dict[str, dict[str, str]] | list[str] | None
    # Container working directory
    working_dir: str
    # Network mode used to start the container
    network_mode: NetworkMode


# ---- Docker helpers ----


def _init_docker() -> docker.DockerClient:
    return docker.from_env()


def _shell_join(cmd: Iterable[str]) -> str:
    return shlex.join(list(cmd))


class NetworkMode(StrEnum):
    NONE = "none"
    BRIDGE = "bridge"
    HOST = "host"


@dataclass
class ContainerOptions:
    image: str
    working_dir: str = "/workspace"
    volumes: dict[str, dict[str, str]] | list[str] | None = None
    network_mode: NetworkMode = NetworkMode.NONE
    environment: dict[str, str] | None = None
    labels: dict[str, str] | None = None
    describe: bool = True


def _session_state_from_ctx(ctx: Any) -> ContainerSessionState:
    return cast(ContainerSessionState, ctx.request_context.lifespan_context)


def _start_container(
    *, client: docker.DockerClient, opts: ContainerOptions
) -> Container:
    return client.containers.run(
        image=opts.image,
        command=SLEEP_FOREVER_CMD,
        detach=True,
        tty=False,
        working_dir=opts.working_dir,
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
        # Start container
        container = _start_container(
            client=client,
            opts=opts,
        )
        try:
            yield ContainerSessionState(
                docker_client=client,
                container=container,
                image=opts.image,
                volumes=opts.volumes,
                working_dir=opts.working_dir,
                network_mode=opts.network_mode,
            )
        finally:
            container.stop(timeout=1)

    return lifespan


# Module-level ExecInput to avoid ForwardRef issues during FastMCP signature introspection


# ---- Register exec tool and resources on a FastMCP server ----


def register_container(mcp: FastMCP, *, tool_name: str = "exec") -> None:
    """Register both container.info resource and exec tool on a FastMCP server.

    This folds resource and tool registration into a single call to avoid double registration.
    """

    # Resource: single JSON describing container/session
    @mcp.resource(
        "resource://container.info",
        mime_type="application/json",
        name="container.info",
        title="Container session metadata",
        description="Docker container details for this session",
    )
    def container_info_json() -> dict[str, Any]:
        ctx = mcp.get_context()
        s = _session_state_from_ctx(ctx)
        img = s.docker_client.images.get(s.image)
        return {
            "image": {"name": s.image, "id": img.id, "tags": img.tags},
            "volumes": s.volumes,
            "working_dir": s.working_dir,
            "network_mode": s.network_mode.value,
            "image_history": cast(Any, s.docker_client.api).history(img.id),
        }

    # Tool: container exec (flat MCP payload, validated via ExecInput)
    @mcp_flat_model(
        mcp,
        name=tool_name,
        title="Execute a command inside the container",
        description="Run a shell command inside the per-session Docker container.",
        structured_output=True,
    )
    def tool_exec(input: ExecInput) -> ExecResult:
        ctx = mcp.get_context()
        s = _session_state_from_ctx(ctx)
        prepared_cmd: list[str] | str
        if input.timeout_secs and input.timeout_secs > 0:
            int_secs = max(1, int(math.ceil(input.timeout_secs)))
            timeout_prefix = f"timeout -s TERM {int_secs} "
            if input.shell:
                # Build a shell string; wrapping to sh -lc happens below if needed
                prepared_cmd = f"{timeout_prefix}{_shell_join(input.cmd)}"
            else:
                # No shell requested → run under sh -lc with timeout prefix
                prepared_cmd = [
                    "sh",
                    "-lc",
                    f"{timeout_prefix}{_shell_join(input.cmd)}",
                ]
        else:
            prepared_cmd = _shell_join(input.cmd) if input.shell else input.cmd

        exec_cmd: list[str] | str
        if (
            input.shell
            and not (
                isinstance(prepared_cmd, list) and prepared_cmd[:2] == ["sh", "-lc"]
            )
            and not isinstance(prepared_cmd, list)
        ):
            exec_cmd_list: list[str] = ["sh", "-lc", prepared_cmd]
            exec_cmd = exec_cmd_list
        else:
            exec_cmd = prepared_cmd

        # Docker SDK types: container.client may be DockerClient or APIClient depending on usage
        cli = s.container.client
        if cli is None:  # mypy: Container.client can be Optional in stubs
            raise RuntimeError("Docker client not available on container")
        if isinstance(cli, docker.APIClient):
            api: docker.APIClient = cli
        else:
            api = cli.api  # type: ignore[assignment]
        exec_kwargs: dict[str, Any] = {
            "container": s.container.id,
            "cmd": exec_cmd,
            "stdout": True,
            "stderr": True,
            "stdin": False,
            "tty": input.tty,
            "workdir": input.cwd,
            "environment": input.env,
        }
        if input.user is not None:
            exec_kwargs["user"] = input.user

        exec_id = api.exec_create(**exec_kwargs)["Id"]

        stdout_buf = bytearray()
        stderr_buf = bytearray()

        for out_err in api.exec_start(exec_id, stream=True, demux=True):
            if not isinstance(out_err, tuple):
                if out_err:
                    stdout_buf.extend(out_err)
                continue
            out_b, err_b = out_err
            if out_b:
                stdout_buf.extend(out_b)
            if err_b:
                stderr_buf.extend(err_b)

        inspect_info = api.exec_inspect(exec_id)
        exit_code = inspect_info.get("ExitCode")

        timed_out = bool(input.timeout_secs) and exit_code == EXIT_CODE_SIGTERM
        if timed_out:
            exit_code = None
        return ExecResult(
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout_buf.decode(errors="replace"),
            stderr=stderr_buf.decode(errors="replace"),
        )
