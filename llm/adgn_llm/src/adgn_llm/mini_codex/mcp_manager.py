from __future__ import annotations

"""
MCP client facade for mini_codex (async version).

Provides long-lived stdio MCP sessions managed on the app's async event loop.

Requirements:
- pip install "mcp[cli]"
- Optional: MCP_CONFIG env var or explicit path passed to from_config()

Namespacing: tools are exposed as "mcp:{server}.{tool}".
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Iterable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .local_server import LocalServer
import shlex
from pathlib import Path


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


class _LiveServer:
    def __init__(self, name: str, cfg: Mapping[str, Any]):
        self.name = name
        self.cfg = cfg
        # Build per-server stderr log path and wrap command to redirect stderr (always on)
        log_dir = Path(os.environ.get("MINICODEX_MCP_LOG_DIR") or (Path(os.getcwd()) / "logs" / "mcp"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Fallback: use current working directory if we cannot create the preferred log directory
            log_dir = Path(os.getcwd())
        log_file = log_dir / f"{_sanitize_name(self.name)}.stderr.log"

        cmd = str(cfg["command"])
        args_list = [str(a) for a in (cfg.get("args") or [])]
        env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}

        shell = os.environ.get("SHELL") or "/bin/sh"
        joined = " ".join([shlex.quote(cmd), *[shlex.quote(a) for a in args_list]])
        command = shell
        args_for_shell = ["-lc", f"exec {joined} 2>> {shlex.quote(str(log_file))}"]

        self._stdio_cm = stdio_client(
            StdioServerParameters(
                command=command,
                args=args_for_shell,
                env=env,
            )
        )
        self._read = None
        self._write = None
        self.session: ClientSession | None = None
        self.info: dict[str, str] = {}

    async def start(self) -> None:
        self._read, self._write = await self._stdio_cm.__aenter__()
        session = ClientSession(self._read, self._write)
        await session.__aenter__()
        init = await session.initialize()
        info = getattr(init, "serverInfo", None)
        self.info = {
            "name": str(getattr(info, "name", self.name)) if info else self.name,
            "version": str(getattr(info, "version", "")) if info else "",
            "description": str(getattr(info, "description", "")) if info else "",
        }
        self.session = session

    async def close(self) -> None:
        if self.session is not None:
            await self.session.__aexit__(None, None, None)
            self.session = None
        if self._stdio_cm is not None:
            await self._stdio_cm.__aexit__(None, None, None)
            self._stdio_cm = None


def _sanitize_name(name: str) -> str:
    import re
    # Allow only letters, digits, underscore, dash
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]

async def _collect_tools_live(
    handles: Mapping[str, _LiveServer],
    local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] | None = None,
):
    openai_tools: list[dict[str, Any]] = []
    reverse: dict[str, tuple[str, str, str]] = {}
    server_infos: dict[str, dict[str, str]] = {}
    for server, h in handles.items():
        assert h.session is not None
        res = await h.session.list_tools()
        server_infos[server] = h.info
        for tool in res.tools:
            params_schema: Mapping[str, Any] = tool.inputSchema or {"type": "object", "properties": {}}
            sanitized = _sanitize_name(f"mcp__{server}__{tool.name}")
            openai_tools.append(
                {
                    "type": "function",
                    "name": sanitized,
                    "description": tool.description or "",
                    "parameters": params_schema,
                }
            )
            reverse[sanitized] = ("stdio", server, tool.name)
    if local_tools:
        for (server, tool_name), (desc, params_schema, _handler) in local_tools.items():
            sanitized = _sanitize_name(f"mcp__{server}__{tool_name}")
            openai_tools.append(
                {
                    "type": "function",
                    "name": sanitized,
                    "description": desc or "",
                    "parameters": params_schema or {"type": "object", "properties": {}},
                }
            )
            reverse[sanitized] = ("local", server, tool_name)
    return server_infos, openai_tools, reverse


async def _call_mcp_tool_live(session: ClientSession, tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    result = await session.call_tool(name=tool_name, arguments=args or {})
    if getattr(result, "isError", False):
        # Extract error message from content blocks when available
        err_text = ""
        if getattr(result, "content", None):
            parts: list[str] = []
            for item in result.content:
                if hasattr(item, "text") and isinstance(item.text, str):
                    parts.append(item.text)
            err_text = "\n".join(parts)
        return {"exit": 2, "stdout": "", "stderr": err_text or "Tool error"}
    if getattr(result, "structuredContent", None) is not None:
        return {"exit": 0, "stdout": "", "stderr": "", "json": result.structuredContent}
    text = ""
    if getattr(result, "content", None):
        parts: list[str] = []
        for item in result.content:
            if hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
        text = "\n".join(parts)
    return {"exit": 0, "stdout": text, "stderr": ""}


@dataclass
class _State:
    handles: dict[str, _LiveServer]
    servers: dict[str, Mapping[str, Any]]
    server_infos: dict[str, dict[str, str]]
    openai_tools: list[dict[str, Any]]
    reverse: dict[str, tuple[str, str, str]]  # namespaced -> (kind, server, tool)
    local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]]
    local_servers: list[LocalServer]


class McpManager:
    """Async facade to manage MCP client sessions and tool dispatch."""

    def __init__(self, state: _State) -> None:
        self._state = state

    @classmethod
    async def from_config(
        cls,
        path: str | None = None,
        *,
        local: dict[str, dict[str, tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]]] | None = None,
        local_servers: Iterable[LocalServer] | None = None,
    ) -> "McpManager":
        servers = _load_mcp_config(path)
        handles: dict[str, _LiveServer] = {}
        for name, cfg in servers.items():
            h = _LiveServer(name, cfg)
            await h.start()
            handles[name] = h
        local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] = {}
        if local:
            for server_name, tools in local.items():
                for tool_name, triplet in tools.items():
                    local_tools[(server_name, tool_name)] = triplet
        local_servers_list = list(local_servers) if local_servers else []
        for srv in local_servers_list:
            for tool_name, triplet in srv.get_tools().items():
                local_tools[(srv.name, tool_name)] = triplet
        server_infos, openai_tools, reverse = await _collect_tools_live(handles, local_tools)
        state = _State(
            handles=handles,
            servers=servers,
            server_infos=server_infos,
            openai_tools=openai_tools,
            reverse=reverse,
            local_tools=local_tools,
            local_servers=local_servers_list,
        )
        return cls(state)

    @classmethod
    async def from_servers(
        cls,
        servers: dict[str, Any],
        *,
        local: dict[str, dict[str, tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]]] | None = None,
        local_servers: Iterable[LocalServer] | None = None,
    ) -> "McpManager":
        servers = servers or {}
        handles: dict[str, _LiveServer] = {}
        for name, cfg in servers.items():
            h = _LiveServer(name, cfg)
            await h.start()
            handles[name] = h
        local_tools: dict[tuple[str, str], tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]] = {}
        if local:
            for server_name, tools in local.items():
                for tool_name, triplet in tools.items():
                    local_tools[(server_name, tool_name)] = triplet
        local_servers_list = list(local_servers) if local_servers else []
        for srv in local_servers_list:
            for tool_name, triplet in srv.get_tools().items():
                local_tools[(srv.name, tool_name)] = triplet
        server_infos, openai_tools, reverse = await _collect_tools_live(handles, local_tools)
        state = _State(
            handles=handles,
            servers=servers,
            server_infos=server_infos,
            openai_tools=openai_tools,
            reverse=reverse,
            local_tools=local_tools,
            local_servers=local_servers_list,
        )
        return cls(state)

    def list_tools(self) -> list[dict[str, Any]]:
        return self._state.openai_tools

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._state.reverse

    async def call_tool(self, function_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        mapping = self._state.reverse
        if function_name not in mapping:
            return {"exit": 127, "stdout": "", "stderr": f"unknown MCP function: {function_name}"}
        kind, server, tool = mapping[function_name]
        if kind == "stdio":
            h = self._state.handles[server]
            assert h.session is not None
            return await _call_mcp_tool_live(h.session, tool, args or {})
        # local in-process handler
        handler_t = self._state.local_tools.get((server, tool))
        if not handler_t:
            return {"exit": 127, "stdout": "", "stderr": f"unknown local MCP function: {function_name}"}
        _desc, _schema, handler = handler_t
        try:
            out = handler(args or {})
            if isinstance(out, dict):
                return {"exit": 0, "stdout": "", "stderr": "", "json": out}
            return {"exit": 0, "stdout": str(out), "stderr": ""}
        except Exception as e:
            return {"exit": 2, "stdout": "", "stderr": f"local tool error: {e}"}

    def instruction_block(self) -> str:
        if not self._state.server_infos:
            return "MCP: no configured servers."
        lines = ["MCP servers:"]
        for key, info in sorted(self._state.server_infos.items()):
            name = info.get("name", key)
            ver = info.get("version", "")
            desc = info.get("description", "")
            line = f"- {key}: {name} {('v'+ver) if ver else ''}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        return "\n".join(lines)

    async def close(self) -> None:
        for h in self._state.handles.values():
            await h.close()
