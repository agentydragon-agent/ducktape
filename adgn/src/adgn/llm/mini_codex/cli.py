from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Any

import openai
import typer

from adgn.llm.logging_config import configure_logging
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler, NotificationsHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui.server import create_app

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

# Typer Option defaults must not be created in function signatures (ruff B008)
MODEL_OPT = typer.Option(DEFAULT_MODEL, "--model", help="Model name (OPENAI_MODEL)")
SYSTEM_OPT = typer.Option(
    SYSTEM_INSTRUCTIONS, "--system", help="System instructions (SYSTEM_INSTRUCTIONS)"
)
MCP_CONFIG_OPT = typer.Option(
    None,
    "--mcp-config",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
    resolve_path=True,
    envvar="MCP_CONFIG",
    help="Path to .mcp.json; defaults to CWD/.mcp.json",
)
EXTRA_MCP_CONFIG_OPT = typer.Option(
    [],
    "--extra-mcp-config",
    help="Additional .mcp.json file(s) to merge (can be passed multiple times)",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
    resolve_path=True,
)
HOST_OPT = typer.Option("127.0.0.1", "--host", help="Host to bind UI server")
PORT_OPT = typer.Option(8765, "--port", help="Port to bind UI server")


def load_mcp_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json: mcpServers must be object")
    return dict(servers)


def _build_specs(mcp_config: Path | None, extra: list[Path]) -> dict[str, Any]:
    cfg_path = mcp_config if mcp_config else (Path.cwd() / ".mcp.json")
    specs: dict[str, Any] = {}
    # If user explicitly provided --mcp-config and it doesn't exist, fail fast
    if mcp_config is not None and not cfg_path.exists():
        raise FileNotFoundError(f"--mcp-config not found: {cfg_path}")
    if cfg_path.exists():
        specs.update(McpManager.slots_from_specs(load_mcp_file(cfg_path)))
    for p in extra or []:
        if not p.exists():
            raise FileNotFoundError(f"--extra-mcp-config not found: {p}")
        specs.update(McpManager.slots_from_specs(load_mcp_file(p)))
    return specs


async def _run_repl_async(
    model: str, system: str, mcp_config: Path | None, extra_mcp: list[Path]
) -> None:
    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    specs = _build_specs(mcp_config, extra_mcp)
    enabled = list(specs.keys())
    print("MCP servers enabled:", ", ".join(enabled) if enabled else "<none>")

    client = openai.AsyncOpenAI()

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=system,
            client=client,
            handlers=[NotificationsHandler(mcp), AutoHandler(), DisplayEventsHandler()],
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
    mcp_config: Path | None = MCP_CONFIG_OPT,
    extra_mcp: list[Path] = EXTRA_MCP_CONFIG_OPT,
) -> None:
    """Start a simple stdin/stdout REPL."""
    asyncio.run(
        _run_repl_async(
            model=model, system=system, mcp_config=mcp_config, extra_mcp=extra_mcp
        )
    )


async def _serve_async(
    host: str,
    port: int,
    model: str,
    system: str,
    mcp_config: Path | None,
    extra_mcp: list[Path],
) -> None:
    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)

    print("mini-codex serve: starting agent + UI server")

    specs = _build_specs(mcp_config, extra_mcp)
    enabled = list(specs.keys())
    print("MCP servers enabled:", ", ".join(enabled) if enabled else "<none>")

    # Build the FastAPI app and attach an agent factory so the agent (and MCP manager)
    # are created on the uvicorn event loop thread, avoiding cross-loop awaits.
    app = create_app()

    async def _agent_factory() -> MiniCodex:
        # Create independent client/manager bound to the uvicorn loop
        inner_client = openai.AsyncOpenAI()
        inner_mcp = McpManager(specs)
        await inner_mcp.__aenter__()
        agent = await MiniCodex.create(
            model=model,
            mcp=inner_mcp,
            system=system,
            client=inner_client,
            handlers=[
                NotificationsHandler(inner_mcp),
                AutoHandler(),
                DisplayEventsHandler(),
            ],
        )
        # Stash for potential shutdown handling (future)
        app.state._inner_mcp = inner_mcp
        app.state._inner_agent = agent
        return agent

    app.state.agent_factory = _agent_factory

    def _run() -> None:
        import uvicorn

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
    system: str = SYSTEM_OPT,
    mcp_config: Path | None = MCP_CONFIG_OPT,
    extra_mcp: list[Path] = EXTRA_MCP_CONFIG_OPT,
) -> None:
    """Launch the local FastAPI UI server and keep running."""
    asyncio.run(
        _serve_async(
            host=host,
            port=port,
            model=model,
            system=system,
            mcp_config=mcp_config,
            extra_mcp=extra_mcp,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
