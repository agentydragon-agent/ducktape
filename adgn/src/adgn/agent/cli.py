from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import urlunparse

from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
import typer
from typer.main import get_command
import uvicorn

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.reducer import AutoHandler
from adgn.agent.server.app import create_app
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.agent.server.system_message import get_ui_system_message
from adgn.llm.logging_config import configure_logging
from adgn.mcp._shared.config_loader import build_mcp_config
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client

# Defaults via environment with sensible fallbacks
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS", "You are a code agent. Use tools to execute commands. Respond with helpful, concise text."
)

app = typer.Typer(help="Mini Codex CLI — run an agent REPL or launch the local UI server.", no_args_is_help=True)

# For the HTML UI, prefer the composed UI system message when the caller
# does not provide an override. Keep REPL behavior unchanged.


def _effective_ui_system(system: str | None) -> str:
    # Typing: guard against Any/None; always return str
    if isinstance(system, str):
        s = str(system).strip()
        if s:
            return s
    return str(get_ui_system_message())


# Typer Option defaults must not be created in function signatures (ruff B008)
MODEL_OPT = typer.Option(DEFAULT_MODEL, "--model", help="Model name (OPENAI_MODEL)")
SYSTEM_OPT = typer.Option(SYSTEM_INSTRUCTIONS, "--system", help="System instructions (SYSTEM_INSTRUCTIONS)")
MCP_CONFIGS_OPT = typer.Option(
    [],
    "--mcp-config",
    help="Additional .mcp.json file(s) to merge (repeatable). Baseline: CWD/.mcp.json is always loaded if present.",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
    resolve_path=True,
)
HOST_OPT = typer.Option("127.0.0.1", "--host", help="Host to bind UI server")
PORT_OPT = typer.Option(8765, "--port", help="Port to bind UI server")
FRONTEND_PORT_OPT = typer.Option(5173, "--frontend-port", help="Port for Vite dev server")


def _pick_free_port(start: int, host: str = "127.0.0.1", max_tries: int = 100) -> int:
    """Return the first available TCP port >= start on host.

    Best-effort check by binding a socket briefly; race is acceptable in dev.
    """
    for p in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
            except OSError:
                continue
            return p
    return start


def _print_enabled(servers: list[str]) -> None:
    print("MCP servers enabled:", ", ".join(servers) if servers else "<none>")
    print("Tip: prefer HTTP specs; inproc factory specs are embedded over HTTP")


def _configure_logging_info() -> None:
    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)


def _configure_logging_debug() -> None:
    """Configure logging with DEBUG level on console for UI commands to show OpenAI traffic."""
    configure_logging()
    logging.getLogger().setLevel(logging.DEBUG)
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.DEBUG)
    # Trim noise from very chatty libraries while keeping our own DEBUG
    # aiosqlite is especially verbose (execute/fetchmany/close per call). Suppress DEBUG by default.
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    # Other common noisy loggers
    logging.getLogger("watchfiles").setLevel(logging.INFO)
    logging.getLogger("websockets.client").setLevel(logging.INFO)
    logging.getLogger("websockets.server").setLevel(logging.INFO)


def _make_handlers(*, ui_bus: ServerBus | None = None, poll_notifications=None) -> list[Any]:
    # UI mode: use ServerModeHandler with notifications poller when provided
    if ui_bus is not None and callable(poll_notifications):
        return [ServerModeHandler(bus=ui_bus, poll_notifications=poll_notifications), DisplayEventsHandler()]
    # Headless/default: allow agent to sample normally via AutoHandler
    return [AutoHandler(), DisplayEventsHandler()]


def _build_cfg_and_print(mcp_configs: list[Path]) -> MCPConfig:
    cfg = build_mcp_config(mcp_configs)
    _print_enabled(list(cfg.mcpServers.keys()))
    return cfg


async def _run_repl_async(model: str, system: str, mcp_configs: list[Path]) -> None:
    _configure_logging_info()
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    cfg = _build_cfg_and_print(mcp_configs)

    client = build_client(model)

    comp = Compositor("compositor")
    for name, spec in cfg.mcpServers.items():
        await comp.mount_server(name, spec)
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            model=model, mcp_client=mcp_client, system=system, client=client, handlers=_make_handlers()
        )
        async with agent:
            for line in sys.stdin:
                user = line.rstrip("\n")
                if not user:
                    continue
                res = await agent.run(user_text=user)
                if res.text:
                    print(res.text)


@app.command("run")
def run(model: str = MODEL_OPT, system: str = SYSTEM_OPT, mcp_configs: list[Path] = MCP_CONFIGS_OPT) -> None:
    """Start a simple stdin/stdout REPL."""
    asyncio.run(_run_repl_async(model=model, system=system, mcp_configs=mcp_configs))


async def _serve_async(host: str, port: int, model: str, system: str | None, mcp_configs: list[Path]) -> None:
    _configure_logging_debug()  # Enable DEBUG logging to show OpenAI traffic

    print("mini-codex serve: starting agent + UI server")

    _ = _build_cfg_and_print(mcp_configs)
    app = create_app()

    def _run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="debug")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"UI server running at http://{host}:{port}")

    # Keep process alive; UI drives runs via WebSocket
    await asyncio.Event().wait()


@app.command("serve")
def serve(
    host: str = HOST_OPT,
    port: int = PORT_OPT,
    model: str = MODEL_OPT,
    system: str | None = typer.Option(None, "--system", help="Override default UI system instructions"),
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
) -> None:
    """Launch the local FastAPI UI server and keep running."""
    asyncio.run(_serve_async(host=host, port=port, model=model, system=system, mcp_configs=mcp_configs))


@app.command("dev")
def dev(
    host: str = HOST_OPT,
    port: int = PORT_OPT,
    frontend_port: int = FRONTEND_PORT_OPT,
    model: str = MODEL_OPT,
    system: str | None = typer.Option(None, "--system", help="Override default UI system instructions"),
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Run dev mode: Vite frontend (HMR) + backend in one command."""
    _configure_logging_debug()  # Enable DEBUG logging to show OpenAI traffic

    # UI has moved to src/adgn/agent/web
    web_dir = Path(__file__).parent / "web"
    if not (web_dir / "package.json").exists():
        typer.echo(f"web UI directory not found: {web_dir}")
        raise typer.Exit(code=2)

    # Print merged config for visibility; the UI will attach via presets/API
    _ = _build_cfg_and_print(mcp_configs)

    # Pick free ports starting from requested bases
    backend_port = _pick_free_port(port, host)
    frontend_dev_port = _pick_free_port(frontend_port, host)
    if backend_port != port:
        typer.echo(f"Port {port} busy, using {backend_port} for backend")
    if frontend_dev_port != frontend_port:
        typer.echo(f"Port {frontend_port} busy, using {frontend_dev_port} for frontend")

    # Prepare Vite environment so frontend can reach backend on a different port
    vite_env = os.environ.copy()

    vite_env["VITE_BACKEND_ORIGIN"] = urlunparse(("http", f"{host}:{backend_port}", "", "", "", ""))

    # Start Vite dev server (HMR)
    vite_cmd = ["npm", "--prefix", str(web_dir), "run", "dev", "--", "--port", str(frontend_dev_port), "--strictPort"]
    typer.echo(f"Starting Vite dev server: {' '.join(vite_cmd)}")
    try:
        vite_proc = subprocess.Popen(vite_cmd, env=vite_env)
    except FileNotFoundError:
        typer.echo("npm not found. Please install Node/npm for frontend dev mode.")
        raise typer.Exit(code=2)

    try:
        url = urlunparse(("http", f"{host}:{frontend_dev_port}", "", "", "", ""))
        typer.echo(f"Frontend (HMR): {url}")
        backend_url = urlunparse(("http", f"{host}:{backend_port}", "", "", "", ""))
        typer.echo(f"Backend (WS/API): {backend_url}")
        if open_browser:
            with contextlib.suppress(Exception):
                subprocess.Popen(["open", url])

        # Build FastAPI app; agent lifecycle is handled by the runtime container (registry)
        app_fastapi = create_app()

        # Run uvicorn (restart this command when backend changes for now)
        uvicorn.run(app_fastapi, host=host, port=backend_port, log_level="debug")
    finally:
        with contextlib.suppress(Exception):
            vite_proc.terminate()
        with contextlib.suppress(Exception):
            vite_proc.wait(timeout=5)


main = get_command(app)

if __name__ == "__main__":
    main()
