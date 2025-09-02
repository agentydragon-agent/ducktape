from __future__ import annotations

"""
MCP client facade for mini_codex.

Provides a synchronous wrapper around the async MCP Python SDK using an anyio
BlockingPortal so the existing CLI can stay synchronous.

Requirements:
- pip install "mcp[cli]"
- Optional: MCP_CONFIG env var or explicit path passed to from_config()

Namespacing: tools are exposed as "mcp:{server}.{tool}".
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
import contextlib

import anyio
from anyio.from_thread import start_blocking_portal, BlockingPortal
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _load_mcp_config(path: str | None) -> dict[str, Any]:
    """Load .mcp.json; return the mcpServers map or {} if file missing.

    Precedence: explicit path -> $MCP_CONFIG -> ./ .mcp.json
    """
    if not path:
        path = os.environ.get("MCP_CONFIG") or os.path.join(os.getcwd(), ".mcp.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    servers = cfg.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError("Invalid .mcp.json: 'mcpServers' must be an object")
    return servers


async def _connect_one(name: str, cfg: Mapping[str, Any]) -> tuple[ClientSession, dict[str, str]]:
    params = StdioServerParameters(
        command=str(cfg["command"]),
        args=[str(a) for a in (cfg.get("args") or [])],
        env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
    )
    # stdio_client is an async context; keep session open until explicitly closed
    read, write = await stdio_client(params).__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    init = await session.initialize()
    info = getattr(init, "serverInfo", None)
    desc = getattr(info, "description", "") if info is not None else ""
    name_f = getattr(info, "name", name) if info is not None else name
    ver = getattr(info, "version", "") if info is not None else ""
    return session, {"name": str(name_f), "version": str(ver), "description": str(desc)}


async def _list_all_tools(sessions_by_server: Mapping[str, ClientSession], local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] | None = None):
    openai_tools: list[dict[str, Any]] = []
    reverse: dict[str, tuple[str, str, str]] = {}  # namespaced -> (kind, server, tool)
    # stdio-backed servers
    for server, session in sessions_by_server.items():
        res = await session.list_tools()
        for tool in res.tools:
            params_schema: Mapping[str, Any] = tool.inputSchema or {"type": "object", "properties": {}}
            name = f"mcp:{server}.{tool.name}"
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description or "",
                        "parameters": params_schema,
                    },
                }
            )
            reverse[name] = ("stdio", server, tool.name)
    # in-process local tools
    if local_tools:
        for (server, tool_name), (desc, params_schema, _handler) in local_tools.items():
            name = f"mcp:{server}.{tool_name}"
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc or "",
                        "parameters": params_schema or {"type": "object", "properties": {}},
                    },
                }
            )
            reverse[name] = ("local", server, tool_name)
    return openai_tools, reverse


async def _call_mcp_tool(session: ClientSession, tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    # Note: read_timeout_seconds can be tuned; keep generous default
    result = await session.call_tool(name=tool_name, arguments=args or {})
    # Normalize into the same envelope mini_codex expects (exit/stdout/stderr or json)
    if getattr(result, "isError", False):
        return {"exit": 2, "stdout": "", "stderr": result.error or "Tool error"}
    if getattr(result, "structuredContent", None) is not None:
        return {"exit": 0, "stdout": "", "stderr": "", "json": result.structuredContent}
    text = ""
    if getattr(result, "content", None):
        parts: list[str] = []
        for item in result.content:
            # Text blocks have .text attribute per spec
            if hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
        text = "\n".join(parts)
    return {"exit": 0, "stdout": text, "stderr": ""}


@dataclass
class _State:
    portal: BlockingPortal
    portal_cm: contextlib.AbstractContextManager[BlockingPortal]
    sessions: dict[str, ClientSession]
    server_infos: dict[str, dict[str, str]]
    openai_tools: list[dict[str, Any]]
    reverse: dict[str, tuple[str, str, str]]  # namespaced -> (kind, server, tool)
    local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]]


class McpManager:
    """Synchronous facade to manage MCP client sessions and tool dispatch.

    Acts as a Null Object when no servers are configured.
    """

    def __init__(self, state: _State) -> None:
        self._state = state

    @classmethod
    def from_config(cls, path: str | None = None) -> "McpManager":
        servers = _load_mcp_config(path)
        # Always bring up a portal for a consistent interface, even with 0 servers
        portal_cm = start_blocking_portal()
        portal = portal_cm.__enter__()
        try:
            sessions: dict[str, ClientSession] = {}
            server_infos: dict[str, dict[str, str]] = {}
            local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] = {}
            # Connect servers sequentially for simplicity; can parallelize later
            for name, cfg in servers.items():
                session, info = portal.call(_connect_one, name, cfg)
                sessions[name] = session
                server_infos[name] = info
            openai_tools, reverse = portal.call(_list_all_tools, sessions, local_tools)
            state = _State(
                portal=portal,
                portal_cm=portal_cm,
                sessions=sessions,
                server_infos=server_infos,
                openai_tools=openai_tools,
                reverse=reverse,
                local_tools=local_tools,
            )
            return cls(state)
        except BaseException:
            # Ensure portal is torn down on init failure
            portal_cm.__exit__(None, None, None)
            raise

    @classmethod
    def from_servers(cls, servers: dict[str, Any], *, local: dict[str, dict[str, tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]]] | None = None) -> "McpManager":
        """Construct directly from a servers mapping, optionally with in-process local tools.

        local shape: {server: {tool: (description, parameters_schema, handler)}}
        """
        portal_cm = start_blocking_portal()
        portal = portal_cm.__enter__()
        try:
            sessions: dict[str, ClientSession] = {}
            server_infos: dict[str, dict[str, str]] = {}
            for name, cfg in servers.items():
                session, info = portal.call(_connect_one, name, cfg)
                sessions[name] = session
                server_infos[name] = info
            local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] = {}
            if local:
                for server_name, tools in local.items():
                    for tool_name, triplet in tools.items():
                        local_tools[(server_name, tool_name)] = triplet
            openai_tools, reverse = portal.call(_list_all_tools, sessions, local_tools)
            state = _State(
                portal=portal,
                portal_cm=portal_cm,
                sessions=sessions,
                server_infos=server_infos,
                openai_tools=openai_tools,
                reverse=reverse,
                local_tools=local_tools,
            )
            return cls(state)
        except BaseException:
            portal_cm.__exit__(None, None, None)
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        return self._state.openai_tools

    def call_tool(self, namespaced: str, args: dict[str, Any] | None) -> dict[str, Any]:
        mapping = self._state.reverse
        if namespaced not in mapping:
            return {"exit": 127, "stdout": "", "stderr": f"unknown MCP function: {namespaced}"}
        kind, server, tool = mapping[namespaced]
        if kind == "stdio":
            session = self._state.sessions[server]
            return self._state.portal.call(_call_mcp_tool, session, tool, args or {})
        # local in-process handler
        handler_t = self._state.local_tools.get((server, tool))
        if not handler_t:
            return {"exit": 127, "stdout": "", "stderr": f"unknown local MCP function: {namespaced}"}
        _desc, _schema, handler = handler_t
        try:
            out = handler(args or {})
            if isinstance(out, dict):
                return {"exit": 0, "stdout": "", "stderr": "", "json": out}
            return {"exit": 0, "stdout": str(out), "stderr": ""}
        except Exception as e:
            return {"exit": 2, "stdout": "", "stderr": f"local tool error: {e}"}

    def instruction_block(self) -> str:
        """Return a concise description of configured MCP servers (server-provided).

        Uses initialize().serverInfo (name/version/optional description), not tool list.
        """
        infos = self._state.server_infos
        if not infos:
            return "MCP: no configured servers."
        lines = ["MCP servers:"]
        for key, info in sorted(infos.items()):
            name = info.get("name", key)
            ver = info.get("version", "")
            desc = info.get("description", "")
            line = f"- {key}: {name} {('v'+ver) if ver else ''}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        return "\n".join(lines)

    def close(self) -> None:
        # Close sessions and stop portal
        for s in self._state.sessions.values():
            try:
                self._state.portal.call(s.aclose)
            except BaseException:
                # Best-effort close
                pass
        self._state.portal_cm.__exit__(None, None, None)
