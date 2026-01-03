#!/usr/bin/env python3
"""
Hetzner Cloud VNC Console Screenshot Tool

Connects to Hetzner's WebSocket-based VNC console and captures a screenshot.

Usage:
    # With server name (requires HCLOUD_TOKEN env var):
    uv run vnc-screenshot.py my-server-name

    # With explicit credentials:
    uv run vnc-screenshot.py --url <wss_url> --password <password>
"""
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "asyncvnc",
#     "pillow",
#     "typer",
#     "hcloud",
#     "websockets",
# ]
# ///

import asyncio
import os
from pathlib import Path
from typing import Annotated

import asyncvnc
import typer
import websockets
from hcloud import Client
from PIL import Image


def request_console_credentials(server_name: str, token: str | None = None) -> tuple[str, str]:
    """Request VNC console credentials from Hetzner Cloud API."""
    if token is None:
        token = os.environ.get("HCLOUD_TOKEN")
        if not token:
            raise ValueError("HCLOUD_TOKEN environment variable not set and no --token provided")

    client = Client(token=token)
    servers = client.servers.get_all(name=server_name)
    if not servers:
        raise ValueError(f"Server '{server_name}' not found")

    response = client.servers.request_console(servers[0])
    return response.wss_url, response.password


async def vnc_screenshot(wss_url: str, password: str, output_path: str = "screenshot.png"):
    """Connect to VNC over WebSocket and capture a screenshot."""
    print(f"Connecting to {wss_url[:80]}...")

    # asyncvnc doesn't directly support wss:// URLs with path tokens,
    # so we establish websocket connection first then hand off to asyncvnc
    async with websockets.connect(wss_url, subprotocols=["binary"]) as ws:
        # Wrap the websocket for asyncvnc
        client = await asyncvnc.Client.create(reader=ws, writer=ws, password=password)

        print(f"Connected. Screen: {client.video.width}x{client.video.height}")
        pixels = await client.screenshot()
        img = Image.fromarray(pixels)
        img.save(output_path)
        print(f"Screenshot saved to {output_path}")


app = typer.Typer(help="Hetzner VNC console screenshot tool")


@app.command()
def main(
    server: Annotated[str | None, typer.Argument(help="Server name (requires HCLOUD_TOKEN env var)")] = None,
    url: Annotated[str | None, typer.Option(help="WebSocket URL (from 'hcloud server request-console')")] = None,
    password: Annotated[str | None, typer.Option(help="VNC password")] = None,
    token: Annotated[str | None, typer.Option(help="Hetzner API token (default: HCLOUD_TOKEN env)")] = None,
    output: Annotated[Path, typer.Option(help="Output image path")] = Path("screenshot.png"),
):
    """Capture a screenshot from Hetzner Cloud VNC console.

    Either provide a server name (uses Hetzner API to get console credentials)
    or provide --url and --password explicitly.
    """
    if server:
        if url or password:
            raise typer.BadParameter("Cannot use --url/--password with server name argument")
        wss_url, vnc_password = request_console_credentials(server, token)
        print(f"Got console credentials for server '{server}'")
    elif url and password:
        wss_url, vnc_password = url, password
    else:
        raise typer.BadParameter("Provide either server name or both --url and --password")

    asyncio.run(vnc_screenshot(wss_url, vnc_password, str(output)))


if __name__ == "__main__":
    app()
