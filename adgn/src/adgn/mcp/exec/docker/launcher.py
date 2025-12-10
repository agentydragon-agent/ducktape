#!/usr/bin/env python3


"""CLI to run the docker_exec MCP server via stdio transport."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import aiodocker
import typer
from typer_di import Depends, TyperDI

from adgn.cli_utils import async_run
from adgn.props.cli.resources import get_async_docker_client

from ..._shared.container_session import ContainerOptions
from ..._shared.types import NetworkMode
from .server import ContainerExecServer

app = TyperDI(help="Run docker_exec MCP over stdio")


def _parse_binds(values: list[str] | None) -> dict[str, dict[str, str]] | None:
    """Parse bind mount specifications into Docker mount format.

    Args:
        values: List of bind specs in format "host:container[:mode]"

    Returns:
        Dict mapping resolved host paths to mount specs, or None if no binds

    Raises:
        typer.BadParameter: If bind spec format is invalid
    """
    if not values:
        return None
    result: dict[str, dict[str, str]] = {}
    entries: list[str] = []
    for value in values:
        entries.extend(value.split(","))
    for entry in entries:
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            raise typer.BadParameter(f"Invalid bind mount spec '{entry}'. Use host:container[:mode].")
        host, container, *mode = parts
        spec: dict[str, str] = {"bind": container}
        if mode:
            spec["mode"] = mode[0]
        result[str(Path(host).resolve())] = spec
    return result


def _parse_labels(label_values: list[str] | None) -> dict[str, str] | None:
    """Parse label key=value pairs into a dict.

    Args:
        label_values: List of "key=value" strings

    Returns:
        Dict of labels, or None if no labels provided

    Raises:
        typer.BadParameter: If label format is invalid
    """
    if not label_values:
        return None
    labels: dict[str, str] = {}
    for raw_label in label_values:
        if "=" not in raw_label:
            raise typer.BadParameter(f"Invalid label '{raw_label}'. Expected key=value format.")
        key, value = raw_label.split("=", 1)
        labels[key] = value
    return labels


@app.command()
@async_run
async def main(
    image: Annotated[str, typer.Option(help="Docker image for session containers")],
    working_dir: Annotated[str, typer.Option(help="Working directory inside the container")] = "/workspace",
    network_mode: Annotated[NetworkMode, typer.Option(help="Docker network mode")] = NetworkMode.NONE,
    binds: Annotated[
        list[str] | None,
        typer.Option(
            help="Bind mount specification host:container[:mode]. May be supplied multiple times or as comma-separated entries."
        ),
    ] = None,
    label: Annotated[
        list[str] | None, typer.Option(help="Docker label to apply to the container (key=value). May be repeated.")
    ] = None,
    ephemeral: Annotated[
        bool, typer.Option(help="Run each command in a fresh ephemeral container with host-enforced timeouts")
    ] = False,
    docker_client: aiodocker.Docker = Depends(get_async_docker_client),  # noqa: B008
) -> None:
    """Run docker_exec MCP server over stdio transport."""
    binds_dict = _parse_binds(binds)
    labels_dict = _parse_labels(label)

    opts = ContainerOptions(
        image=image,
        working_dir=Path(working_dir),
        binds=binds_dict,
        network_mode=network_mode,
        labels=labels_dict,
        ephemeral=ephemeral,
    )

    try:
        server = ContainerExecServer(opts, docker_client)
        await server.run_stdio_async()
    finally:
        await docker_client.close()


if __name__ == "__main__":
    app()
