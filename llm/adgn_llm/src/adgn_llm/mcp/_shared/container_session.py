from __future__ import annotations

import shlex
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Iterable, cast

import docker
from docker.errors import APIError
from docker.models.containers import Container
from mcp.server.fastmcp import FastMCP

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


def _start_container(
    *,
    client: docker.DockerClient,
    image: str,
    working_dir: str,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    network_mode: NetworkMode = NetworkMode.NONE,
    environment: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
) -> Container:
    from adgn_llm.properties.docker_env import SLEEP_FOREVER_CMD  # local import to avoid cycles

    container = client.containers.run(
        image=image,
        command=SLEEP_FOREVER_CMD,
        detach=True,
        tty=False,
        working_dir=working_dir,
        network_mode=str(network_mode),
        volumes=volumes,
        environment=environment,
        labels=labels,
        # Run as image default user (root by default). No override.
        auto_remove=True,
    )
    return container


def _container_exec(
    *,
    container: Container,
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    user: str | None = None,
    tty: bool = False,
    shell: bool = False,
    timeout_secs: float | None = None,
) -> dict[str, Any]:
    prepared_cmd: list[str] | str
    if timeout_secs and timeout_secs > 0:
        timeout_arg = f"timeout -s TERM {int(timeout_secs)}"
        if shell:
            prepared_cmd = f"{timeout_arg} {_shell_join(cmd)}"
        else:
            prepared_cmd = ["sh", "-lc", f"{timeout_arg} {_shell_join(cmd)}"]
    else:
        prepared_cmd = _shell_join(cmd) if shell else cmd

    if (
        shell
        and not (isinstance(prepared_cmd, list) and prepared_cmd[:2] == ["sh", "-lc"])
        and not isinstance(prepared_cmd, list)
    ):
        exec_cmd: list[str] | str = ["sh", "-lc", prepared_cmd]  # type: ignore[list-item]
    else:
        exec_cmd = prepared_cmd

    cli = container.client
    if cli is None:  # mypy: Container.client can be Optional in stubs
        raise RuntimeError("Docker client not available on container")
    api = cast(Any, cli).api  # DockerClient.api → low-level APIClient; use Any for compatibility with stubs
    exec_id = api.exec_create(
        container=container.id,
        cmd=exec_cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=tty,
        user=user,
        workdir=cwd,
        environment=env,
    )["Id"]

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

    try:
        inspect_info = api.exec_inspect(exec_id)
        exit_code = inspect_info.get("ExitCode")
    except APIError:
        exit_code = None

    timed_out = bool(timeout_secs) and exit_code == 143
    if timed_out:
        exit_code = None
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout_buf.decode(errors="replace"),
        "stderr": stderr_buf.decode(errors="replace"),
    }


# ---- Lifespan factory (per-session container) ----


def make_container_lifespan(
    *,
    image: str,
    working_dir: str = "/workspace",
    describe: bool = True,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
    network_mode: NetworkMode = NetworkMode.NONE,
    environment: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
):
    @asynccontextmanager
    async def lifespan(server: FastMCP):  # yields ContainerSessionState
        client = _init_docker()
        # Start container
        container = _start_container(
            client=client,
            image=image,
            working_dir=working_dir,
            volumes=volumes,
            network_mode=network_mode,
            environment=environment,
            labels=labels,
        )
        try:
            yield ContainerSessionState(
                docker_client=client,
                container=container,
                image=image,
                volumes=volumes,
                working_dir=working_dir,
                network_mode=network_mode,
            )
        finally:
            container.stop(timeout=1)

    return lifespan


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
    def container_info_json() -> Dict[str, Any]:
        ctx = mcp.get_context()
        s: ContainerSessionState = ctx.request_context.lifespan_context  # type: ignore[assignment]
        img = s.docker_client.images.get(s.image)
        return {
            "image": {"name": s.image, "id": img.id, "tags": img.tags},
            "volumes": s.volumes,
            "working_dir": s.working_dir,
            "network_mode": s.network_mode.value,
            "image_history": s.docker_client.api.history(img.id),  # type: ignore[attr-defined]
        }

    # Tool: container exec
    @mcp.tool(
        name=tool_name,
        title="Execute a command inside the container",
        description="Run a shell command inside the per-session Docker container.",
        structured_output=True,
    )
    def tool_exec(
        cmd: list[str],
        cwd: str | None = None,
        env: Dict[str, str] | None = None,
        user: str | None = None,
        tty: bool = False,
        shell: bool = False,
        timeout_secs: float | None = None,
    ) -> dict[str, Any]:
        ctx = mcp.get_context()
        s = ctx.request_context.lifespan_context  # type: ignore[assignment]
        return _container_exec(
            container=s.container,
            cmd=cmd,
            cwd=cwd,
            env=env,
            user=user,
            tty=tty,
            shell=shell,
            timeout_secs=timeout_secs,
        )
