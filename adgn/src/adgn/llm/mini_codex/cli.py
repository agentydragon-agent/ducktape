from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Any

import openai

from adgn.llm.logging_config import configure_logging
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.local_exec.server import make_local_exec_mcp
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui.server import run_uvicorn, session

LOCAL_EXEC_SERVER_NAME = "local"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS",
    "You are a code agent. Use tools to execute commands. Respond with helpful, concise text.",
)


def load_mcp_file(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json: mcpServers must be object")
    return dict(servers)


async def main_async() -> None:
    # Ensure consistent logging; bump console to INFO for this CLI
    configure_logging()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.INFO)
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    # Build specs: load stdio MCP servers from config if available + local exec
    cfg_path_env = os.environ.get("MCP_CONFIG")
    cfg_path = Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")

    specs: dict[str, Any] = {}

    # Add local in-process exec server via FastMCP memory streams (in-proc JSON-RPC)
    specs[LOCAL_EXEC_SERVER_NAME] = make_inproc_slot_spec(
        make_local_exec_mcp(LOCAL_EXEC_SERVER_NAME),
    )

    # Add servers from config via unified slots_from_specs (requires explicit transport for remote servers)
    if cfg_path.exists():
        specs.update(McpManager.slots_from_specs(load_mcp_file(str(cfg_path))))

    client = openai.AsyncOpenAI()

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=DEFAULT_MODEL,
            mcp=mcp,
            system=SYSTEM_INSTRUCTIONS,
            client=client,
            handlers=[AutoHandler(), DisplayEventsHandler()],
        )
        async with agent:
            for line in sys.stdin:
                user = line.rstrip("\n")
                if not user:
                    continue
                res = await agent.run(user_text=user)
                if res.text:
                    print(res.text)


def main() -> None:
    # support subcommand: 'serve' to launch UI server attached to agent
    if len(sys.argv) > 1 and sys.argv[1] == "serve":

        async def main_async_serve() -> None:
            configure_logging()
            for h in logging.getLogger().handlers:
                if isinstance(h, logging.StreamHandler):
                    h.setLevel(logging.INFO)
            # Parse extra args for serve (e.g., --port, --host)
            parser = argparse.ArgumentParser(prog="mini-codex serve", add_help=False)
            parser.add_argument("--port", type=int, default=8765)
            parser.add_argument("--host", type=str, default="127.0.0.1")
            args, _ = parser.parse_known_args(sys.argv[2:])
            print("mini-codex serve: starting agent + UI server")

            cfg_path_env = os.environ.get("MCP_CONFIG")
            cfg_path = (
                Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")
            )

            specs: dict[str, Any] = {}
            specs[LOCAL_EXEC_SERVER_NAME] = make_inproc_slot_spec(
                make_local_exec_mcp(LOCAL_EXEC_SERVER_NAME),
            )
            if cfg_path.exists():
                specs.update(McpManager.slots_from_specs(load_mcp_file(str(cfg_path))))

            client = openai.AsyncOpenAI()

            async with McpManager(specs) as mcp:
                agent = await MiniCodex.create(
                    model=DEFAULT_MODEL,
                    mcp=mcp,
                    system=SYSTEM_INSTRUCTIONS,
                    client=client,
                    handlers=[AutoHandler(), DisplayEventsHandler()],
                )

                # Attach agent to UI session

                session.attach_agent(agent)

                # Start uvicorn in background thread

                t = threading.Thread(
                    target=run_uvicorn,
                    kwargs={"host": args.host, "port": args.port},
                    daemon=True,
                )
                t.start()
                print(f"UI server running at http://{args.host}:{args.port}")

                async with agent:
                    # In serve mode, keep process alive; UI drives runs via WebSocket
                    await asyncio.Event().wait()

        asyncio.run(main_async_serve())
    else:
        asyncio.run(main_async())


if __name__ == "__main__":
    main()
