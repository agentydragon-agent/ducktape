from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, cast

import openai
from adgn_llm.logging_config import configure_logging
from pydantic import BaseModel

from adgn_llm.mini_codex.agent import (
    load_mcp_file,
    MiniCodex,
    AgentResult,
)
from adgn_llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn_llm.mcp.local_exec.server import make_local_exec_mcp
from adgn_llm.mini_codex.mcp_manager import (
    McpManager,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec

LOCAL_EXEC_SERVER_NAME = "local"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
DEFAULT_TIMEOUT_S = int(os.getenv("DUCK_TIMEOUT_S", "30"))
TRUNCATE_BYTES = 8 * 1024
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS",
    ("You are a code agent. Use tools to execute commands. Respond with helpful, concise text."),
)

BWRAP = os.getenv("BWRAP", "bwrap")
ALLOW_UNSHARE_NET = os.getenv("DUCK_UNSHARE_NET", "0") == "1"
ALLOW_UNSANDBOXED = os.getenv("DUCK_ALLOW_UNSANDBOXED", "0") == "1"  # dev-mode fallback on non-Linux
API_MAX_RETRIES = int(os.getenv("DUCK_API_MAX_RETRIES", "2"))
MAX_CYCLES = int(os.getenv("DUCK_MAX_CYCLES", "8"))


class ExecError(Exception):
    pass


# ==== Pydantic models for transcript messages ====
class UserMessage(BaseModel):
    role: Literal["user"]
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str


class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"]
    call_id: str
    output: str


Message = UserMessage | AssistantMessage | FunctionCallOutput


def dump_messages_for_api(messages: list[Message]) -> list[dict[str, Any]]:
    # Serialize Pydantic models to plain dicts suitable for the Responses API
    return [m.model_dump(exclude_none=True) for m in messages]


def _truncate_bytes(s: str, limit: int) -> str:
    """Truncate a string by UTF-8 bytes, appending a marker if needed.

    Note: limit is in bytes; we avoid splitting multibyte characters.
    """
    data = s.encode("utf-8")
    if len(data) <= limit:
        return s
    marker = b"\n[TRUNCATED]"
    if limit <= len(marker):
        return "[TRUNCATED]"
    head = data[: limit - len(marker)]
    return head.decode("utf-8", errors="ignore") + "\n[TRUNCATED]"


def _run_proc(
    argv: list[str],
    timeout_s: int,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    p = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return (
            124,
            _truncate_bytes(out, TRUNCATE_BYTES),
            _truncate_bytes(err + "\n[TIMEOUT]", TRUNCATE_BYTES),
        )

    return (
        p.returncode,
        _truncate_bytes(out, TRUNCATE_BYTES),
        _truncate_bytes(err, TRUNCATE_BYTES),
    )


async def main_async() -> None:
    # Ensure consistent logging (quiet console, optional file)
    configure_logging()
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    # Build specs: load stdio MCP servers from config if available + local exec
    cfg_path_env = os.environ.get("MCP_CONFIG")
    cfg_path = Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")

    specs = {}

    # Add local in-process exec server via FastMCP memory streams (in-proc JSON-RPC)
    specs[LOCAL_EXEC_SERVER_NAME] = make_inproc_slot_spec(make_local_exec_mcp(LOCAL_EXEC_SERVER_NAME))

    # Add servers from config via unified slots_from_specs (requires explicit transport for remote servers)
    if cfg_path.exists():
        servers = load_mcp_file(str(cfg_path))
        if isinstance(servers, dict):
            specs.update(McpManager.slots_from_specs(servers))

    client = openai.AsyncOpenAI()

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=DEFAULT_MODEL,
            mcp=mcp,
            system=SYSTEM_INSTRUCTIONS,
            client=client,
            handlers=[DisplayEventsHandler()],
        )
        async with agent:
            for line in sys.stdin:
                user = line.rstrip("\n")
                if not user:
                    continue
                res = cast(AgentResult, await agent.run(user_text=user, stream=False))
                if res.text:
                    print(res.text)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
