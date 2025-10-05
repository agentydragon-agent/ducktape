from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from pydantic import TypeAdapter
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.runtime.specs import McpServerSpec
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.llm.logging_config import configure_logging
from adgn.mcp._shared.container_session import ContainerOptions, NetworkMode
from adgn.mcp.docker_exec.server import (
    SERVER_NAME as DOCKER_SERVER,
    make_container_exec_mcp,
)
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.matrix.control import make_matrix_control_mcp
from adgn.openai_utils.client_factory import build_client

app = typer.Typer(
    help="Matrix-driven MiniCodex entrypoint (docker + yield-only control)",
    no_args_is_help=True,
)


def _configure_logging_info() -> None:
    configure_logging()


def _load_mcp_file(path: Path) -> dict[str, McpServerSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json: mcpServers must be object")
    TA = TypeAdapter(dict[str, McpServerSpec])
    return TA.validate_python(servers)


def _build_specs(mcp_configs: list[Path]) -> dict[str, McpServerSpec]:
    baseline = Path.cwd() / ".mcp.json"
    specs: dict[str, McpServerSpec] = {}
    if baseline.exists():
        specs.update(_load_mcp_file(baseline))
    for p in mcp_configs or []:
        if not p.exists():
            raise FileNotFoundError(f"--mcp-config not found: {p}")
        specs.update(_load_mcp_file(p))
    return specs


@app.command()
def run(
    model: str = typer.Option(os.getenv("OPENAI_MODEL", "o4-mini"), "--model"),
    mcp_configs: list[Path] = typer.Option(
        [],
        "--mcp-config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    homeserver: str = typer.Option(..., "--homeserver", help="Matrix homeserver base URL"),
    user_id: str = typer.Option(..., "--user-id", help="Matrix user id (e.g. @bot:example.com)"),
    access_token: str = typer.Option(..., "--access-token", help="Matrix access token"),
    room: str = typer.Option(
        ..., "--room", help="Room id or alias to watch (#alias:server or !id:server)"
    ),
    docker_image: str = typer.Option(
        os.getenv("MATRIX_DOCKER_IMAGE", "curlimages/curl:8.8.0"), "--docker-image"
    ),
    network_mode: str = typer.Option(os.getenv("MATRIX_DOCKER_NETWORK", "bridge"), "--network"),
    system: str | None = typer.Option(
        None, "--system", help="Override default system instructions"
    ),
    initial_since: str | None = typer.Option(os.getenv("MATRIX_SINCE"), "--since"),
) -> None:
    """Run MiniCodex in headless Matrix mode using docker_exec + yield-only control."""

    async def _run() -> None:
        _configure_logging_info()

        specs = _build_specs(mcp_configs)
        ui_bus = ServerBus()

        nm = (
            NetworkMode(network_mode)
            if network_mode in ("none", "bridge", "host")
            else NetworkMode.BRIDGE
        )
        env = {
            "MATRIX_BASE_URL": homeserver,
            "MATRIX_ACCESS_TOKEN": access_token,
            "MATRIX_ROOM_ID": room,
            "MATRIX_USER_ID": user_id,
        }
        docker_mcp = make_container_exec_mcp(
            ContainerOptions(image=docker_image, network_mode=nm, environment=env)
        )
        docker_spec = make_inproc_slot_spec(docker_mcp)
        control_spec = make_inproc_slot_spec(make_matrix_control_mcp("matrix_control", ui_bus))

        effective_system = (system or "").strip() or (
            "You are a Matrix-driven assistant. Do not emit plain text.\n"
            "I/O contract:\n"
            "- Use mcp__docker__docker_exec to call Matrix HTTP APIs (curl) or your CLI from inside the container.\n"
            "- Read new DMs, send replies, and when finished call mcp__matrix_control__yield().\n"
            "- Do not emit plain text; only use tools.\n"
        )

        client = build_client(model)

        async with McpManager(specs) as mcp:
            await mcp.attach_server(DOCKER_SERVER, docker_spec)
            await mcp.attach_server("matrix_control", control_spec)
            agent = await MiniCodex.create(
                model=model,
                mcp=mcp,
                system=effective_system,
                client=client,
                handlers=[
                    ServerModeHandler(bus=ui_bus, poll_notifications=mcp.poll_notifications),
                    DisplayEventsHandler(),
                ],
            )

            async def _sync_once(since: str | None) -> tuple[str, bool]:
                qs = {"timeout": "30000"}
                if since:
                    qs["since"] = since
                url = f"$MATRIX_BASE_URL/_matrix/client/v3/sync?{urlencode(qs)}"
                hdr = "Authorization: Bearer $MATRIX_ACCESS_TOKEN"
                cmd = [
                    "sh",
                    "-lc",
                    f'curl -sS -H {json.dumps(hdr)} --fail --max-time 35 "{url}"',
                ]
                res = await mcp.call_tool_namespaced(
                    "mcp__docker__docker_exec", {"cmd": cmd, "timeout_secs": 40}
                )
                payload = res.structuredContent or {}
                stdout = (payload or {}).get("stdout") or ""
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
