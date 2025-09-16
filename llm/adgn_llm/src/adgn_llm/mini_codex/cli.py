from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import openai
from adgn_llm.logging_config import configure_logging
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.local_exec.server import make_local_exec_mcp
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import AutoHandler
from adgn_llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mini_codex.ui.server import run_uvicorn, session

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
    # Ensure consistent logging (quiet console, optional file)
    configure_logging()
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    # Build specs: load stdio MCP servers from config if available + local exec
    cfg_path_env = os.environ.get("MCP_CONFIG")
    cfg_path = Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")

    specs: dict[str, Any] = {}

    # Add local in-process exec server via FastMCP memory streams (in-proc JSON-RPC)
    specs[LOCAL_EXEC_SERVER_NAME] = make_inproc_slot_spec(make_local_exec_mcp(LOCAL_EXEC_SERVER_NAME))

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
            print("mini-codex serve: starting agent + UI server")

            cfg_path_env = os.environ.get("MCP_CONFIG")
            cfg_path = Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")

            specs: dict[str, Any] = {}
            specs[LOCAL_EXEC_SERVER_NAME] = make_inproc_slot_spec(make_local_exec_mcp(LOCAL_EXEC_SERVER_NAME))
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

                t = threading.Thread(target=run_uvicorn, daemon=True)
                t.start()
                print("UI server running at http://127.0.0.1:8765")

                async with agent:
                    for line in sys.stdin:
                        user = line.rstrip("\n")
                        if not user:
                            continue
                        res = await agent.run(user_text=user)
                        if res.text:
                            print(res.text)

        asyncio.run(main_async_serve())
    else:
        asyncio.run(main_async())


if __name__ == "__main__":
    main()
