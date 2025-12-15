"""Shared resources for CLI commands (dependency injection providers).

This module provides dependency functions for expensive resources that should be
created once per CLI invocation and reused across commands.

typer-di automatically caches these dependencies - each function is called once
per CLI invocation and the result is reused. This avoids:
- Repeated SnapshotHydrator.from_env() (expensive: loads all manifests)

Usage in commands:
    from typer_di import Depends
    from .resources import get_hydrator

    @app.command()
    def my_command(
        snapshot: str,
        hydrator: SnapshotHydrator = Depends(get_hydrator),
    ):
        # hydrator is injected automatically
        # typer-di ensures get_hydrator() is called only once per CLI invocation
        ...
"""

from __future__ import annotations

from ..db.config import DatabaseConfig, get_database_config as _get_database_config
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


def get_database_config() -> DatabaseConfig:
    """Get database configuration from environment variables.

    Reads PostgreSQL connection parameters from environment (set by devenv or passed to containers).

    typer-di calls this function only once per CLI invocation.
    """
    return _get_database_config()


# NOTE: No get_docker_client() dependency function.
#
# CLI commands create aiodocker.Docker() clients locally in async context.
# typer-di doesn't support async dependencies - they must be created
# inside the async command function.
#
# Example:
#
#   async def my_command(...):
#       async with aiodocker.Docker() as docker_client:
#           # use docker_client
#           ...
#
# This ensures the Docker client is created inside the running event loop.
