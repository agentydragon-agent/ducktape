from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from typing import Any

from pydantic import TypeAdapter
import typer
from typer.main import get_command
import uvicorn

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler, NotificationsHandler
from adgn.agent.runtime.handlers import build_handlers
from adgn.agent.runtime.specs import McpServerSpec
from adgn.agent.server.app import create_app
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.agent.server.runtime import ConnectionManager
from adgn.agent.server.system_message import get_ui_system_message
from adgn.llm.logging_config import configure_logging
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.ui.server import make_ui_mcp
from adgn.openai_utils.client_factory import build_client

# Defaults via environment with sensible fallbacks
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS",
    "You are a code agent. Use tools to execute commands. Respond with helpful, concise text.",
)

app = typer.Typer(
    help="Mini Codex CLI — run an agent REPL or launch the local UI server.",
    no_args_is_help=True,
)

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
SYSTEM_OPT = typer.Option(
    SYSTEM_INSTRUCTIONS, "--system", help="System instructions (SYSTEM_INSTRUCTIONS)"
)
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
    print("Tip: for inproc servers, see src/adgn/agent/example.mcp.json")


def _configure_logging_info() -> None:
    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)


def _configure_logging_debug() -> None:
    """Configure logging with DEBUG level on console for UI commands to show OpenAI traffic."""
    configure_logging()
    # Set root logger level to DEBUG
    logging.getLogger().setLevel(logging.DEBUG)
    # Set console handler to DEBUG
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


def _make_handlers(mcp: McpManager, ui_bus: ServerBus | None = None) -> list[Any]:
    # UI mode: single handler for notifications + RequireAny
    if ui_bus is not None:
        return [
            ServerModeHandler(bus=ui_bus, poll_notifications=mcp.poll_notifications),
            DisplayEventsHandler(),
        ]
    # Headless/default: allow agent to sample normally via AutoHandler
    return [AutoHandler(), NotificationsHandler(mcp), DisplayEventsHandler()]


def _build_specs_and_print(mcp_configs: list[Path]) -> dict[str, McpServerSpec]:
    specs = _build_specs(mcp_configs)
    _print_enabled(list(specs.keys()))
    return specs


def load_mcp_file(path: Path) -> dict[str, McpServerSpec]:
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
        specs.update(load_mcp_file(baseline))
    for p in mcp_configs or []:
        if not p.exists():
            raise FileNotFoundError(f"--mcp-config not found: {p}")
        specs.update(load_mcp_file(p))
    return specs


async def _run_repl_async(model: str, system: str, mcp_configs: list[Path]) -> None:
    _configure_logging_info()
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    specs = _build_specs_and_print(mcp_configs)

    # Build our Pydantic-only client with retries at the entrypoint
    client = build_client(model)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=system,
            client=client,
            handlers=_make_handlers(mcp),
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
def run(
    model: str = MODEL_OPT,
    system: str = SYSTEM_OPT,
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
) -> None:
    """Start a simple stdin/stdout REPL."""
    asyncio.run(_run_repl_async(model=model, system=system, mcp_configs=mcp_configs))


async def _serve_async(
    host: str,
    port: int,
    model: str,
    system: str | None,
    mcp_configs: list[Path],
) -> None:
    _configure_logging_debug()  # Enable DEBUG logging to show OpenAI traffic

    print("mini-codex serve: starting agent + UI server")

    specs = _build_specs_and_print(mcp_configs)
    # Create per-agent UI bus and prepare in-proc UI server separately
    ui_bus = ServerBus()
    ui_spec = make_inproc_slot_spec(make_ui_mcp("ui", ui_bus))

    # Create approval system components
    approval_engine = ApprovalPolicyEngine()
    approval_hub = ApprovalHub()

    # Add the approval policy MCP server so the agent can manage policies
    approval_server = ApprovalPolicyServer(approval_engine)
    # Apply a short initialize timeout to surface init issues quickly
    approval_spec = make_inproc_slot_spec(approval_server, init_timeout_secs=2)

    # Build the FastAPI app and attach an agent factory so the agent (and MCP manager)
    # are created on the uvicorn event loop thread, avoiding cross-loop awaits.
    app = create_app()
    # expose per-agent UI bus to the UI server for draining/snapshotting
    app.state.ui_bus = ui_bus
    # Wire approval engine so the UI can access it
    app.state.approval_engine = approval_engine
    app.state.approval_hub = approval_hub

    async def _agent_factory() -> MiniCodex:
        # Create independent client/manager bound to the uvicorn loop
        inner_client = build_client(model, enable_debug_logging=True)
        inner_mcp = McpManager(specs)
        await inner_mcp.__aenter__()
        # Attach in-proc servers (UI and approval) after manager is entered
        await inner_mcp.attach_server("ui", ui_spec)
        await inner_mcp.attach_server("approval_policy", approval_spec)
        # Build handlers using shared builder
        manager = ConnectionManager()
        persist = app.state.persistence

        def _get_run_id() -> str | None:
            sess = app.state.session
            return sess.active_run.run_id if sess.active_run else None

        handlers, persist_handler, _ = build_handlers(
            mcp=inner_mcp,
            manager=manager,
            persistence=persist,
            approval_engine=approval_engine,
            approval_hub=approval_hub,
            get_run_id=_get_run_id,
            ui_bus=ui_bus,
        )
        agent = await MiniCodex.create(
            model=model,
            mcp=inner_mcp,
            system=_effective_ui_system(system),
            client=inner_client,
            handlers=handlers,
        )
        # CLI environment may not expose a session; handlers are attached regardless.
        # Stash for potential shutdown handling (future)
        app.state._inner_mcp = inner_mcp
        app.state._inner_agent = agent
        return agent

    app.state.agent_factory = _agent_factory

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
    system: str | None = typer.Option(
        None, "--system", help="Override default UI system instructions"
    ),
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
) -> None:
    """Launch the local FastAPI UI server and keep running."""
    asyncio.run(
        _serve_async(
            host=host,
            port=port,
            model=model,
            system=system,
            mcp_configs=mcp_configs,
        )
    )


@app.command("dev")
def dev(
    host: str = HOST_OPT,
    port: int = PORT_OPT,
    frontend_port: int = FRONTEND_PORT_OPT,
    model: str = MODEL_OPT,
    system: str | None = typer.Option(
        None, "--system", help="Override default UI system instructions"
    ),
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

    # Build specs now so the agent factory can reuse them on the uvicorn loop
    specs = _build_specs_and_print(mcp_configs)
    # Create per-agent UI bus; in-proc servers are attached after manager creation
    ui_bus = ServerBus()

    # Pick free ports starting from requested bases
    backend_port = _pick_free_port(port, host)
    frontend_dev_port = _pick_free_port(frontend_port, host)
    if backend_port != port:
        typer.echo(f"Port {port} busy, using {backend_port} for backend")
    if frontend_dev_port != frontend_port:
        typer.echo(f"Port {frontend_port} busy, using {frontend_dev_port} for frontend")

    # Prepare Vite environment so frontend can reach backend on a different port
    vite_env = os.environ.copy()
    vite_env["VITE_BACKEND_ORIGIN"] = f"http://{host}:{backend_port}"

    # Start Vite dev server (HMR)
    vite_cmd = [
        "npm",
        "--prefix",
        str(web_dir),
        "run",
        "dev",
        "--",
        "--port",
        str(frontend_dev_port),
        "--strictPort",
    ]
    typer.echo(f"Starting Vite dev server: {' '.join(vite_cmd)}")
    try:
        vite_proc = subprocess.Popen(vite_cmd, env=vite_env)
    except FileNotFoundError:
        typer.echo("npm not found. Please install Node/npm for frontend dev mode.")
        raise typer.Exit(code=2)

    try:
        url = f"http://{host}:{frontend_dev_port}"
        typer.echo(f"Frontend (HMR): {url}")
        typer.echo(f"Backend (WS/API): http://{host}:{backend_port}")
        if open_browser:
            with contextlib.suppress(Exception):
                subprocess.Popen(["open", url])

        # Create approval system components
        approval_engine = ApprovalPolicyEngine()
        approval_hub = ApprovalHub()

        # Prepare approval policy MCP server for attachment later
        approval_server = ApprovalPolicyServer(approval_engine)

        # Build FastAPI app and attach an agent factory created on the uvicorn loop
        app_fastapi = create_app()
        # expose per-agent UI bus to the UI server for draining/snapshotting
        app_fastapi.state.ui_bus = ui_bus
        # Wire approval system
        app_fastapi.state.approval_engine = approval_engine
        app_fastapi.state.approval_hub = approval_hub

        async def _agent_factory() -> MiniCodex:
            inner_client = build_client(model, enable_debug_logging=True)
            inner_mcp = McpManager(specs)
            await inner_mcp.__aenter__()
            # Attach in-proc UI and approval servers after manager is entered
            await inner_mcp.attach_server(
                "ui",
                make_inproc_slot_spec(make_ui_mcp("ui", ui_bus)),
            )
            await inner_mcp.attach_server(
                "approval_policy",
                make_inproc_slot_spec(approval_server, init_timeout_secs=2),
            )
            manager = ConnectionManager()
            persist = app_fastapi.state.persistence

            def _get_run_id2() -> str | None:
                sess = app_fastapi.state.session
                return sess.active_run.run_id if sess.active_run else None

            handlers, persist_handler2, _ = build_handlers(
                mcp=inner_mcp,
                manager=manager,
                persistence=persist,
                approval_engine=approval_engine,
                approval_hub=approval_hub,
                get_run_id=_get_run_id2,
                ui_bus=ui_bus,
            )
            agent = await MiniCodex.create(
                model=model,
                mcp=inner_mcp,
                system=_effective_ui_system(system),
                client=inner_client,
                handlers=handlers,
            )
            # Dev environment may not expose a session; handlers are attached regardless.
            app_fastapi.state._inner_mcp = inner_mcp
            app_fastapi.state._inner_agent = agent
            return agent

        app_fastapi.state.agent_factory = _agent_factory

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
