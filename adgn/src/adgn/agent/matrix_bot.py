from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from fastmcp.client import Client
from pydantic import TypeAdapter
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.llm.logging_config import configure_logging
from adgn.mcp._shared.calltool import convert_fastmcp_result
from adgn.mcp._shared.config_loader import build_mcp_config
from adgn.mcp._shared.constants import MATRIX_CONTROL_SERVER_NAME
from adgn.mcp._shared.container_session import ContainerOptions, NetworkMode
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.mcp.exec.models import BaseExecResult
from adgn.mcp.matrix.control import make_matrix_control_server
from adgn.mcp.notifications.buffer import NotificationsBuffer
from adgn.openai_utils.client_factory import build_client

app = typer.Typer(help="Matrix-driven MiniCodex entrypoint (docker + yield-only control)", no_args_is_help=True)


def _configure_logging_info() -> None:
    configure_logging()


@app.command()
def run(
    model: str = typer.Option(os.getenv("OPENAI_MODEL", "o4-mini"), "--model"),
    mcp_configs: list[Path] = typer.Option(  # noqa: B008
        [], "--mcp-config", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
    ),
    homeserver: str = typer.Option(..., "--homeserver", help="Matrix homeserver base URL"),
    user_id: str = typer.Option(..., "--user-id", help="Matrix user id (e.g. @bot:example.com)"),
    access_token: str = typer.Option(..., "--access-token", help="Matrix access token"),
    room: str = typer.Option(..., "--room", help="Room id or alias to watch (#alias:server or !id:server)"),
    docker_image: str = typer.Option(os.getenv("MATRIX_DOCKER_IMAGE", "curlimages/curl:8.8.0"), "--docker-image"),
    network_mode: str = typer.Option(os.getenv("MATRIX_DOCKER_NETWORK", "bridge"), "--network"),
    system: str | None = typer.Option(None, "--system", help="Override default system instructions"),
    initial_since: str | None = typer.Option(os.getenv("MATRIX_SINCE"), "--since"),
) -> None:
    """Run MiniCodex in headless Matrix mode using docker_exec + yield-only control."""

    async def _run() -> None:
        _configure_logging_info()

        _ = build_mcp_config(mcp_configs)
        ui_bus = ServerBus()

        nm = NetworkMode(network_mode) if network_mode in ("none", "bridge", "host") else NetworkMode.BRIDGE
        env = {
            "MATRIX_BASE_URL": homeserver,
            "MATRIX_ACCESS_TOKEN": access_token,
            "MATRIX_ROOM_ID": room,
            "MATRIX_USER_ID": user_id,
        }
        docker_exec_tool = build_mcp_function("docker", "exec")
        matrix_yield_tool = build_mcp_function(MATRIX_CONTROL_SERVER_NAME, "yield")
        effective_system = (system or "").strip() or (
            "You are a Matrix-driven assistant. Do not emit plain text.\n"
            "I/O contract:\n"
            f"- Use {docker_exec_tool} to call Matrix HTTP APIs (curl) or your CLI from inside the container.\n"
            f"- Read new DMs, send replies, and when finished call {matrix_yield_tool}().\n"
            "- Do not emit plain text; only use tools.\n"
        )

        client = build_client(model)

        # Build a Compositor and mount runtime + matrix control servers

        comp = Compositor("compositor")
        runtime_server = make_container_exec_server(
            ContainerOptions(image=docker_image, network_mode=nm, environment=env, ephemeral=True)
        )
        await comp.mount_inproc("docker", runtime_server)
        matrix_control = make_matrix_control_server(name="Matrix Control", bus=ui_bus)
        await comp.mount_inproc(MATRIX_CONTROL_SERVER_NAME, matrix_control)

        # Client with notifications buffer so UI can reflect MCP updates
        notif_buffer = NotificationsBuffer(compositor=comp)
        async with Client(comp, message_handler=notif_buffer.handler) as mcp_client:
            agent = await MiniCodex.create(
                model=model,
                mcp_client=mcp_client,
                system=effective_system,
                client=client,
                handlers=[ServerModeHandler(bus=ui_bus, poll_notifications=notif_buffer.poll), DisplayEventsHandler()],
            )

            async def _sync_once(since: str | None) -> tuple[str, bool]:
                qs = {"timeout": "30000"}
                if since:
                    qs["since"] = since
                url = f"$MATRIX_BASE_URL/_matrix/client/v3/sync?{urlencode(qs)}"
                hdr = "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
                cmd = ["sh", "-lc", f'curl -sS -H {json.dumps(hdr)} --fail --max-time 35 "{url}"']
                res_client = await mcp_client.session.call_tool(
                    name=build_mcp_function("docker", "exec"), arguments={"cmd": cmd, "timeout_ms": 40_000}
                )
                res = convert_fastmcp_result(res_client)
                ex = TypeAdapter(BaseExecResult).validate_python(res.structuredContent or {})
                stdout_stream = ex.stdout or ""
                assert isinstance(stdout_stream, str), "Matrix API response should not be truncated"
                stdout = stdout_stream
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError:
                    # Not JSON (or truncated), keep polling without advancing
                    return since or "", False
                next_since = data.get("next_batch") or (since or "")
                rooms = (data.get("rooms") or {}).get("join") or {}
                events = (rooms.get(room) or {}).get("timeline", {}).get("events", [])
                return next_since, bool(events)

            since_token = initial_since or None
            async with agent:
                while True:
                    next_since, has_new = await _sync_once(since_token)
                    since_token = next_since
                    if not has_new:
                        continue
                    await agent.run(user_text="process matrix inbox")

    asyncio.run(_run())


def main() -> None:
    app()
