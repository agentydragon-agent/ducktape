"""CLI to run the docker_exec MCP server via stdio transport.

Accepts a single JSON config file (ContainerExecServerConfig schema).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import aiodocker
import typer
from typer_di import TyperDI

from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.docker.types import ContainerExecServerConfig
from util.typer import async_run

app = TyperDI(help="Run docker_exec MCP over stdio")


@app.command()
@async_run
async def main(
    config_file: Annotated[Path, typer.Argument(help="JSON config file (ContainerExecServerConfig schema)")],
) -> None:
    """Run docker_exec MCP server over stdio transport."""
    config = ContainerExecServerConfig.model_validate_json(config_file.read_text())
    docker_client = aiodocker.Docker()
    try:
        server = ContainerExecServer(docker_client, config)
        await server.run_stdio_async()
    finally:
        await docker_client.close()


if __name__ == "__main__":
    app()
