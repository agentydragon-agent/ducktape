"""Shared resources for CLI commands (dependency injection providers).

This module provides dependency functions for expensive resources that should be
created once per CLI invocation and reused across commands.

typer-di automatically caches these dependencies - each function is called once
per CLI invocation and the result is reused. This avoids:
- Repeated SnapshotHydrator.from_env() (expensive: loads all manifests)
- Repeated docker.from_env() (expensive: connects to Docker daemon)

Usage in commands:
    from typer_di import Depends
    from .resources import get_hydrator, get_docker_client

    @app.command()
    def my_command(
        snapshot: str,
        hydrator: SnapshotHydrator = Depends(get_hydrator),
        docker_client: docker.DockerClient = Depends(get_docker_client),
    ):
        # hydrator and docker_client are injected automatically
        # typer-di ensures get_hydrator() and get_docker_client() are called
        # only once per CLI invocation
        ...
"""

from __future__ import annotations

import atexit

import docker

from ..hydration import SnapshotHydrator


def get_hydrator() -> SnapshotHydrator:
    """Get snapshot hydrator (loads manifests once per CLI invocation).

    Expensive operation:
    - Reads and parses snapshots.yaml
    - Validates all snapshot manifests with Pydantic
    - Builds file type maps

    typer-di calls this function only once per CLI invocation.
    """
    return SnapshotHydrator.from_env()


def get_docker_client() -> docker.DockerClient:
    """Get Docker client (connects once per CLI invocation, cleaned up on exit).

    Expensive operation:
    - Connects to Docker daemon
    - Initializes API client

    typer-di calls this function only once per CLI invocation.
    Cleanup registered with atexit to close connection on CLI exit.
    """
    client = docker.from_env()
    atexit.register(client.close)
    return client


# NOTE: No get_async_docker_client() dependency function here.
#
# aiodocker.Docker() requires a running event loop (it creates aiohttp.UnixConnector
# internally which calls asyncio.get_running_loop()). typer-di does not support
# async dependencies - it calls dependency functions synchronously before the
# async command starts.
#
# Therefore, async commands that need aiodocker.Docker should create it directly:
#
#   async def my_command(...):
#       docker_client = aiodocker.Docker()
#       try:
#           # use docker_client
#           ...
#       finally:
#           await docker_client.close()
#
# This ensures the Docker client is created inside the running event loop.
