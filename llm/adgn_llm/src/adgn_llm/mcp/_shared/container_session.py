from __future__ import annotations

import shlex
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Iterable

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
    container = client.containers.run(
        image=image,
        command=["/bin/sh", "-lc", "sleep infinity"],
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

    exec_id = container.client.api.exec_create(
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

    for out_err in container.client.api.exec_start(exec_id, stream=True, demux=True):
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
        inspect = container.client.api.exec_inspect(exec_id)
        exit_code = inspect.get("ExitCode")
    except APIError:
        exit_code = None

    return {
        "exit_code": exit_code,
        "timed_out": False,
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
        # Compose a host-side description (single source of truth) before starting tools
        if describe:
            img = _init_docker().images.get(image)
            img_id, tags = img.id, img.tags
            hist = _init_docker().api.history(img_id)  # type: ignore[attr-defined]
            history_lines: list[str] = []
            for entry in hist or []:
                created_by = (entry.get("CreatedBy") or "").lstrip("/bin/sh -c ").removeprefix("#(nop) ").strip()
                if created_by:
                    history_lines.append(f"  - {created_by}")

            vol_lines: list[str] = []
            if isinstance(volumes, dict):
                for host, spec in volumes.items():
                    bind = spec.get("bind") if isinstance(spec, dict) else None
                    mode = spec.get("mode") if isinstance(spec, dict) else None
                    if bind:
                        vol_lines.append(f"  - {host} → {bind}{' (' + mode + ')' if mode else ''}")

            desc = [
                "Container session",
                f"- Working dir: {working_dir}",
                f"- Network mode: {network_mode.value}",
                f"- Image: {img_id} {' '.join(tags) if tags else ''}",
                "- Volumes:",
                *(vol_lines or ["  - (none)"]),
                "Image history (CreatedBy):",
                "\n".join(history_lines[:100]) if history_lines else "  - (none)",
            ]
            server.server_info.description = "\n".join(desc)  # type: ignore[attr-defined]

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
    @mcp.resource("resource://container.info", mime_type="application/json", name="container.info")
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
    @mcp.tool(name=tool_name)
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



