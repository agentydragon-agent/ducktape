#!/usr/bin/env python3
"""Docker-based editor CLI.

Runs an LLM agent to edit a single file inside an isolated Docker container.
The agent has access to docker-exec for running commands, and submits the
edited content via the helper script which calls the host-side submit server.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import aiodocker
import typer

from adgn.definition_builder import ensure_image
from adgn.mcp.editor_docker.agent_runner import run_editor_docker_agent
from adgn.mcp.editor_docker.runner import DEFAULT_NETWORK
from adgn.mcp.editor_docker.submit_server import SubmitStateFailure, SubmitStatePending, SubmitStateSuccess
from cli_util import async_run, make_logging_callback
from openai_utils.client_factory import build_client

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1-codex-mini")
DEFINITION_DIR = Path(__file__).parent / "definition"
EDITOR_IMAGE_TAG = "adgn-editor:latest"

# Environment variable override for network
_ENV_NETWORK = os.getenv("ADGN_EDITOR_DOCKER_NETWORK", DEFAULT_NETWORK)

app = typer.Typer(help="Docker-based file editor with LLM agent.")

# Configure logging via shared callback (default: INFO level)
app.callback()(make_logging_callback(default_level="INFO"))

MODEL_OPT = typer.Option(DEFAULT_MODEL, "--model", help="Model name (OPENAI_MODEL)")
NETWORK_OPT = typer.Option(_ENV_NETWORK, "--network", help="Docker network (ADGN_EDITOR_DOCKER_NETWORK)")
MAX_TURNS_OPT = typer.Option(40, "--max-turns", help="Maximum agent turns before abort")


@app.command()
@async_run
async def edit(
    file: Annotated[Path, typer.Argument(help="Path to the file to edit")],
    model: str = MODEL_OPT,
    network: str = NETWORK_OPT,
    max_turns: int = MAX_TURNS_OPT,
) -> None:
    """Edit a file using an LLM agent in an isolated Docker container.

    The agent reads the file content via MCP resource, makes edits using
    docker exec, and submits the final content. On success, the file is
    updated; on failure or abort, the file is left unchanged.
    """
    file = file.resolve()
    if not file.is_file():
        raise typer.BadParameter(f"Not a file: {file}")

    model_client = build_client(model, enable_debug_logging=True)

    async with aiodocker.Docker() as docker_client:
        # Build or reuse editor agent image
        image_id = await ensure_image(docker_client, DEFINITION_DIR, EDITOR_IMAGE_TAG)
        typer.echo(f"Editing {file} with {model} (image {image_id[:12]})")

        result = await run_editor_docker_agent(
            file_path=file,
            docker_client=docker_client,
            model_client=model_client,
            max_turns=max_turns,
            image_id=image_id,
            network=network,
        )

    match result:
        case SubmitStateSuccess():
            typer.echo("Success: file updated.")
        case SubmitStateFailure(message=msg):
            typer.echo(f"Failure: {msg}", err=True)
            raise typer.Exit(code=1)
        case SubmitStatePending():
            typer.echo("Agent did not submit (max turns reached or aborted).", err=True)
            raise typer.Exit(code=2)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
