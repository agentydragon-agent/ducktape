"""Editor CLI tools - init bootstrap and submit commands via MCP."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Annotated

import typer

from agent_pkg_runtime.mcp import mcp_client_from_env
from agent_pkg_runtime.output import render_agent_prompt
from editor_util import EDIT_RESOURCE_URI

submit_app = typer.Typer(name="editor-submit", help="Editor submit helper for MCP communication")


async def _get_filename() -> str:
    """Read target filename from resource metadata."""
    async with mcp_client_from_env() as (client, _init_result):
        resources = await client.list_resources()
        for resource in resources:
            if str(resource.uri) == EDIT_RESOURCE_URI:
                return resource.name
        raise RuntimeError(f"Resource {EDIT_RESOURCE_URI} not found")


async def _read_content() -> str:
    """Read file content from MCP resource."""
    async with mcp_client_from_env() as (client, _init_result):
        contents = await client.read_resource(EDIT_RESOURCE_URI)
        if not contents:
            raise RuntimeError("Resource returned no contents")
        for content in contents:
            if hasattr(content, "text"):
                return content.text
        raise RuntimeError("Resource returned no text content")


@submit_app.command("read-input")
def read_input() -> None:
    """Read the original file content from the MCP server."""
    content = asyncio.run(_read_content())
    sys.stdout.write(content)


@submit_app.command("materialize")
def materialize(
    directory: Annotated[Path, typer.Argument(help="Directory to write file to")] = Path("/workspace"),
) -> None:
    """Materialize the target file to disk and print its path."""
    filename = asyncio.run(_get_filename())
    content = asyncio.run(_read_content())
    target_path = directory / filename
    target_path.write_text(content, encoding="utf-8")
    print(target_path)


async def _submit_success_async(message: str, file_path: Path) -> None:
    content = file_path.read_text(encoding="utf-8")
    async with mcp_client_from_env() as (client, _init_result):
        await client.call_tool("submit_success", {"message": message, "content": content})


@submit_app.command("submit-success")
def submit_success(
    message: Annotated[str, typer.Option("--message", "-m", help="Success message")],
    file: Annotated[Path, typer.Option("--file", "-f", help="Path to file with edited content")],
) -> None:
    """Submit successful edit with the file content."""
    asyncio.run(_submit_success_async(message, file))


async def _submit_failure_async(message: str) -> None:
    async with mcp_client_from_env() as (client, _init_result):
        await client.call_tool("submit_failure", {"message": message})


@submit_app.command("submit-failure")
def submit_failure(message: Annotated[str, typer.Option("--message", "-m", help="Failure message")]) -> None:
    """Submit failure with a message."""
    asyncio.run(_submit_failure_async(message))


@submit_app.command("init")
def init_cmd() -> None:
    """Bootstrap the editor agent environment."""
    render_agent_prompt("editor_util/docs/agent.md")


def main() -> None:
    """Entry point for the editor-submit CLI."""
    submit_app()


if __name__ == "__main__":
    main()
