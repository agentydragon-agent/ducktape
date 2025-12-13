from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import os
from pathlib import Path
import socket
import subprocess
import threading
from urllib.parse import urlencode, urlunparse

from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
from rich.console import Console
from rich.prompt import Prompt
import typer
from typer.main import get_command
import uvicorn

from adgn.agent.agent import Agent
from adgn.agent.compaction_handler import CompactionHandler
from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import FinishOnTextMessageHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage
from adgn.agent.mcp_bridge.auth import TokensConfig
from adgn.agent.server.app import create_app
from adgn.agent.server.system_message import get_ui_system_message
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.cli.logging_callback import make_logging_callback
from adgn.cli_utils import async_run
from adgn.mcp._shared.config_loader import build_mcp_config
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import SystemMessage, UserMessage

# Defaults via environment with sensible fallbacks
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS", "You are a code agent. Use tools to execute commands. Respond with helpful, concise text."
)

app = typer.Typer(help="Mini Codex CLI — run an agent REPL or launch the local UI server.", no_args_is_help=True)

# Configure logging via shared callback (default: INFO level)
app.callback()(make_logging_callback(default_level="INFO"))


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
TRANSCRIPT_OPT = typer.Option(
    None, "--transcript", help="Write full transcript (API requests/responses) to this JSONL file"
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


def _build_cfg_and_print(mcp_configs: list[Path]) -> MCPConfig:
    cfg = build_mcp_config(mcp_configs)
    _print_enabled(list(cfg.mcpServers.keys()))
    return cfg


def _print_auth_url(host: str, port: int) -> None:
    """Print the authenticated URL for accessing the UI."""
    config = TokensConfig.from_yaml_file()
    if user_tokens := config.user_tokens():
        # Use first user token
        token = next(iter(user_tokens.keys()))
        query = urlencode({"token": token})
        url = urlunparse(("http", f"{host}:{port}", "", "", query, ""))
        print(f"\nAuthenticated URL: {url}")
    else:
        print("\nNo user tokens found. Create ~/.config/adgn/tokens.yaml with:")
        print("  users:")
        print('    admin: "your-hex-token"')


@app.command("run")
@async_run
async def run(
    model: str = MODEL_OPT,
    system: str = SYSTEM_OPT,
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
    compact_at_tokens: int | None = typer.Option(
        None, "--compact-at-tokens", help="Enable compaction at this token threshold (e.g., 150000 for 75% of 200k)"
    ),
    transcript: Path | None = TRANSCRIPT_OPT,
) -> None:
    """Start a simple stdin/stdout REPL."""
    console = Console()
    console.print("[bold green]Agent ready.[/] Ctrl-D to exit.", highlight=False)

    cfg = _build_cfg_and_print(mcp_configs)

    # Build model client
    client = build_client(model)

    # Setup transcript path (always write transcript)
    if transcript is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        transcript = Path(f"/tmp/adgn-agent-transcript-{timestamp}.jsonl")
    console.print(f"[dim]Writing transcript to: {transcript}[/dim]")

    # Build in-proc Compositor and mount servers
    # Use Compositor as async context manager to ensure cleanup
    async with Compositor() as comp:
        await comp.mount_servers_from_config(cfg)

        # Build handlers with compact rich display
        # Handler order matters: on_before_sample() returns first non-NoAction decision.
        # CompactionHandler must come before FinishOnTextMessageHandler so it can trigger
        # compaction before the loop aborts (when assistant sends text after hitting threshold).
        handlers: list = []
        if compact_at_tokens is not None:
            handlers.append(CompactionHandler(threshold_tokens=compact_at_tokens))
            console.print(f"[dim]Compaction enabled: will compact at {compact_at_tokens} tokens[/dim]")

        display_handler = await CompactDisplayHandler.from_compositor(comp, console=console)

        handlers.extend([FinishOnTextMessageHandler(), display_handler, TranscriptHandler(events_path=transcript)])

        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=handlers,
                tool_policy=AllowAnyToolOrTextMessage(),
                dynamic_instructions=comp.render_agent_dynamic_instructions,
            )
            agent.insert_message(SystemMessage.text(system))
            while True:
                try:
                    user = Prompt.ask("\n[bold cyan]>[/bold cyan]", console=console)
                    if not user:
                        continue
                    agent.insert_message(UserMessage.text(user))
                    await agent.run()
                except EOFError:
                    console.print("\n[dim]Exiting...[/dim]")
                    break
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here


@app.command("serve")
@async_run
async def serve(host: str = HOST_OPT, port: int = PORT_OPT, mcp_configs: list[Path] = MCP_CONFIGS_OPT) -> None:
    """Launch the local FastAPI UI server and keep running.

    Tip: Use --log-level=DEBUG to show detailed OpenAI traffic.
    """
    print("Agent serve: starting agent + UI server")

    _ = _build_cfg_and_print(mcp_configs)
    # Build the FastAPI app; agent lifecycle is handled by the runtime container (registry)
    fastapi_app = create_app()

    def _run() -> None:
        uvicorn.run(fastapi_app, host=host, port=port, log_level="debug")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"\nUI server running at http://{host}:{port}")
    _print_auth_url(host, port)

    # Keep process alive; UI drives runs via MCP
    await asyncio.Event().wait()


@app.command("dev")
def dev(
    host: str = HOST_OPT,
    port: int = PORT_OPT,
    frontend_port: int = FRONTEND_PORT_OPT,
    mcp_configs: list[Path] = MCP_CONFIGS_OPT,
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Run dev mode: Vite frontend (HMR) + backend in one command.

    Tip: Use --log-level=DEBUG to show detailed OpenAI traffic.
    """
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
        typer.echo(f"Backend (MCP): {backend_url}")
        _print_auth_url(host, frontend_dev_port)
        if open_browser:
            # Try to open authenticated URL if token available
            config = TokensConfig.from_yaml_file()
            if user_tokens := config.user_tokens():
                token = next(iter(user_tokens.keys()))
                query = urlencode({"token": token})
                auth_url = urlunparse(("http", f"{host}:{frontend_dev_port}", "", "", query, ""))
            else:
                auth_url = url
            with contextlib.suppress(Exception):
                subprocess.Popen(["open", auth_url])

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
