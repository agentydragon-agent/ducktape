from __future__ import annotations

import os

import anyio

import docker

from .server import SERVER_NAME, SeatbeltExecMCP


def main() -> None:
    agent_id = os.environ.get("ADGN_AGENT_ID") or "seatbelt-dev"
    dcli = docker.from_env()
    server = SeatbeltExecMCP(SERVER_NAME, agent_id=agent_id, persistence=None, docker_client=dcli)
    anyio.run(server.run_stdio_async)
