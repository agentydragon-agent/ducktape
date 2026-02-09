"""CLI for props dashboard backend."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from cli_util.logging import LogLevel, make_logging_callback
from props.backend.app import create_app, default_deps

logger = logging.getLogger(__name__)

cli = typer.Typer(help="Props dashboard backend")
cli.callback()(make_logging_callback(default_level=LogLevel.INFO))


class _GraderSpawningServer(uvicorn.Server):
    """Server subclass that spawns grader containers after startup completes.

    Avoids the chicken-and-egg problem: grader containers need the registry
    proxy (served by this same HTTP server) to resolve images, so we can
    only start them after uvicorn has bound its socket.
    """

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        # After uvicorn binds, spawn graders for existing snapshots
        supervisor = getattr(self.config.loaded_app, "state", None)
        supervisor = getattr(supervisor, "grader_supervisor", None)
        if supervisor is not None:
            logger.info("HTTP server ready, spawning graders for existing snapshots")
            self._spawn_task = asyncio.create_task(supervisor.spawn_existing(), name="grader-initial-spawn")


@cli.command()
def serve(
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind to")] = 8000,
    reload: Annotated[bool, typer.Option(help="Enable auto-reload for development")] = False,
    reload_dir: Annotated[list[str] | None, typer.Option(help="Directories to watch for reload")] = None,
    static_dir: Annotated[Path | None, typer.Option(help="Directory with static frontend assets")] = None,
) -> None:
    """Start the props dashboard server."""
    if static_dir:
        os.environ["PROPS_DASHBOARD_STATIC_DIR"] = str(static_dir.absolute())

    deps = default_deps(host=host, port=port)
    app = create_app(deps=deps, static_dir=static_dir)

    if reload:
        # Reload mode uses uvicorn.run() which manages its own server instance
        uvicorn.run(app, host=host, port=port, reload=reload, reload_dirs=reload_dir)
    else:
        config = uvicorn.Config(app, host=host, port=port)
        server = _GraderSpawningServer(config)
        asyncio.run(server.serve())


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
