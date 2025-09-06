"""
MCP client facade for MiniCodex — FastMCP-first, sessions-only.

- One abstraction: per-server MCP ClientSession (no local wrappers)
- Namespacing built centrally: mcp__{server}__{tool}
- No legacy wrappers; no stdout/stderr temp formats
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _load_mcp_config(path: str | None) -> dict[str, Any]:
    cfg_path = (
        Path(path)
        if path
        else (
            Path(os.environ.get("MCP_CONFIG", ""))
            if os.environ.get("MCP_CONFIG")
            else (Path.cwd() / ".mcp.json")
        )
    )
    if not cfg_path.exists():
        return {}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    servers = cfg.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError("Invalid .mcp.json: 'mcpServers' must be an object")
    return servers


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]


async def _start_stdio_server(
    name: str, cfg: Mapping[str, Any],
) -> tuple[ClientSession, dict[str, str], Any]:
    """Create and initialize a stdio-backed MCP ClientSession, return (session, info, closer)."""
    cmd = str(cfg["command"])
    args_list = [str(a) for a in (cfg.get("args") or [])]
    env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}

    log_dir = Path(
        os.environ.get("MINICODEX_MCP_LOG_DIR") or (Path.cwd() / "logs" / "mcp"),
    )
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_dir = Path.cwd()
    log_file = log_dir / f"{_sanitize_name(name)}.stderr.log"

    shell = os.environ.get("SHELL") or "/bin/sh"
    joined = " ".join([shlex.quote(cmd), *[shlex.quote(a) for a in args_list]])
    cm = stdio_client(
        StdioServerParameters(
            command=shell,
            args=["-lc", f"exec {joined} 2>> {shlex.quote(str(log_file))}"],
            env=env,
        ),
    )
    read, write = await cm.__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    init = await session.initialize()
    si = getattr(init, "serverInfo", None)  # type: ignore[attr-defined]
    info = {
        "name": getattr(si, "name", name) if si else name,
        "version": getattr(si, "version", "") if si else "",
        "description": getattr(si, "description", "") if si else "",
    }

    async def _close():
        await session.__aexit__(None, None, None)
        await cm.__aexit__(None, None, None)

    return session, info, _close


async def _collect_tools(
    sessions: Mapping[str, ClientSession],
    server_infos: Mapping[str, dict[str, str]],
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    openai_tools: list[dict[str, Any]] = []
    for server, session in sessions.items():
        res = await session.list_tools()
        for t in res.tools or []:
            sanitized = _sanitize_name(f"mcp__{server}__{t.name}")
            params_schema: Mapping[str, Any] = t.inputSchema or {
                "type": "object",
                "properties": {},
            }
            openai_tools.append(
                {
                    "type": "function",
                    "name": sanitized,
                    "description": t.description or "",
                    "parameters": params_schema,
                },
            )
    return dict(server_infos), openai_tools


@dataclass
class ServerRecord:
    session: ClientSession
    close: Any  # async callable
    info: dict[str, str]


class McpManager:
    """Async facade to manage MCP ClientSessions and tool dispatch."""

    async def __aenter__(self) -> "McpManager":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def __init__(
        self,
        *,
        servers: dict[str, ServerRecord],
        openai_tools: list[dict[str, Any]],
    ) -> None:
        self.servers = servers
        self.openai_tools = openai_tools

    @classmethod
    async def from_config(
        cls,
        path: str | None = None,
        *,
        inproc_sessions: Mapping[str, ClientSession] | None = None,
    ) -> McpManager:
        cfg = _load_mcp_config(path)
        servers: dict[str, ServerRecord] = {}
        # stdio-backed
        for name, scfg in cfg.items():
            session, info, closer = await _start_stdio_server(name, scfg)
            servers[name] = ServerRecord(session=session, close=closer, info=info)
        # in-process provided sessions
        for name, sess in (inproc_sessions or {}).items():

            async def _close_s(s: ClientSession = sess):  # bind
                await s.__aexit__(None, None, None)

            servers[name] = ServerRecord(
                session=sess,
                close=_close_s,
                info={"name": name, "version": "", "description": "inproc"},
            )
        server_infos = {name: rec.info for name, rec in servers.items()}
        _, openai_tools = await _collect_tools(
            {name: rec.session for name, rec in servers.items()}, server_infos,
        )
        return cls(servers=servers, openai_tools=openai_tools)

    @classmethod
    async def from_servers(
        cls,
        servers_cfg: dict[str, Any],
        *,
        inproc_sessions: Mapping[str, ClientSession] | None = None,
    ) -> McpManager:
        servers: dict[str, ServerRecord] = {}
        for name, scfg in (servers_cfg or {}).items():
            session, info, closer = await _start_stdio_server(name, scfg)
            servers[name] = ServerRecord(session=session, close=closer, info=info)
        for name, sess in (inproc_sessions or {}).items():

            async def _close_s(s: ClientSession = sess):
                await s.__aexit__(None, None, None)

            servers[name] = ServerRecord(
                session=sess,
                close=_close_s,
                info={"name": name, "version": "", "description": "inproc"},
            )
        server_infos = {name: rec.info for name, rec in servers.items()}
        _, openai_tools = await _collect_tools(
            {name: rec.session for name, rec in servers.items()}, server_infos,
        )
        return cls(servers=servers, openai_tools=openai_tools)

    def list_tools(self) -> list[dict[str, Any]]:
        return self.openai_tools

    def resolve_function(self, namespaced: str) -> tuple[str, str]:
        # namespaced form: mcp__{server}__{tool}
        if not namespaced.startswith("mcp__"):
            raise ValueError(f"Not an MCP tool name: {namespaced}")
        remainder = namespaced[len("mcp__") :]
        if "__" not in remainder:
            raise ValueError(f"Invalid MCP tool name: {namespaced}")
        server, tool = remainder.split("__", 1)
        return server, tool

    def get_session(self, server: str) -> ClientSession:
        return self.servers[server].session

    def instruction_block(self) -> str:
        if not self.servers:
            return "MCP: no configured servers."
        lines = ["MCP servers:"]
        for key, rec in sorted(self.servers.items()):
            name = rec.info.get("name", key)
            ver = rec.info.get("version", "")
            desc = rec.info.get("description", "")
            line = f"- {key}: {name} {('v' + ver) if ver else ''}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        return "\n".join(lines)

    async def close(self) -> None:
        for rec in self.servers.values():
            rc = rec.close()
            if hasattr(rc, "__await__"):
                await rc
