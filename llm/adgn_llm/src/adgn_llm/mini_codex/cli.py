from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from shutil import which
from typing import Any, Literal

import openai
from adgn_llm.mini_codex.agent import (
    MiniCodex,
    _responses_create_with_retry,
    load_mcp_file,
)
from adgn_llm.mini_codex.local_exec_server import LocalExecServer
from adgn_llm.mini_codex.mcp_manager import McpManager
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from pydantic import BaseModel

LOCAL_EXEC_SERVER_NAME = "local"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
DEFAULT_TIMEOUT_S = int(os.getenv("DUCK_TIMEOUT_S", "30"))
TRUNCATE_BYTES = 8 * 1024
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS",
    (
        "You are a code agent. Use the tool shell.run to execute commands. "
        "Respond with helpful, concise text."
    ),
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


def _run_proc(argv: list[str], timeout_s: int, cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd,
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


def run_in_sandbox(
    cmd: list[str], timeout_s: int = DEFAULT_TIMEOUT_S, cwd: str | None = None,
) -> tuple[int, str, str]:
    # Optional dev-mode fallback to run without sandbox on non-Linux
    if sys.platform != "linux":
        if ALLOW_UNSANDBOXED:
            return _run_proc(cmd, timeout_s=timeout_s, cwd=cwd)
        raise ExecError("Sandbox requires Linux (bubblewrap)")
    # Check bwrap exists
    if which(BWRAP) is None:
        raise ExecError("bubblewrap (bwrap) not found in PATH")

    cwd_val = cwd or str(Path.cwd())

    argv: list[str] = [
        BWRAP,
        "--unshare-all",
        "--die-with-parent",
    ]
    if ALLOW_UNSHARE_NET:
        argv.append("--unshare-net")

    argv += [
        "--ro-bind",
        "/",
        "/",
        "--bind",
        cwd_val,
        cwd_val,
        "--chdir",
        cwd_val,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--setenv",
        "HOME",
        "/tmp",
        "--",
        *cmd,
    ]

    # chdir handled inside bwrap; pass cwd=None to subprocess
    return _run_proc(argv, timeout_s=timeout_s, cwd=None)


def openai_client() -> openai.OpenAI:
    # Let the SDK read configuration from environment; no manual key plumbing
    return openai.OpenAI()




async def responses_turn(
    client: openai.OpenAI, messages: list[Message], mcp_manager: McpManager | None = None,
) -> tuple[list[Message], str | None]:
    """Send a single non-streaming turn via Responses API.

    Returns (new_messages, terminal_text). If terminal_text is not None,
    print it to stdout for the user.
    """
    # Include MCP server descriptions in the instructions, if available
    instructions = SYSTEM_INSTRUCTIONS
    if mcp_manager is not None:
        extra = mcp_manager.instruction_block()
        if extra:
            instructions = f"{SYSTEM_INSTRUCTIONS}\n\n{extra}"

    resp = _responses_create_with_retry(
        client,
        model=DEFAULT_MODEL,
        input=dump_messages_for_api(messages),
        instructions=instructions,
        stream=False,
        tool_choice="auto",
        store=False,
        tools=[
            * (mcp_manager.list_tools() if mcp_manager else []),
        ],
    )

    new_messages: list[Message] = []
    terminal_text: str | None = None

    # Collect assistant output items and action requirements
    output = resp.output
    # We only handle messages and function tool calls
    requires: list[ResponseFunctionToolCall] = []
    for item in output:
        if isinstance(item, ResponseOutputMessage):
            # Print assistant text; also add to transcript
            text_parts = []
            for part in item.content:
                if isinstance(part, ResponseOutputText):
                    text_parts.append(part.text)
            combined = "\n".join([p for p in text_parts if p])
            if combined:
                terminal_text = (terminal_text + "\n" if terminal_text else "") + combined
                new_messages.append(AssistantMessage(role="assistant", content=combined))
        elif isinstance(item, ResponseFunctionToolCall):
            requires.append(item)
        # ignore other item types for MVP

    # Execute required tool calls and enqueue function_call_output
    for fc in requires:
        fn = fc.name
        call_id = fc.call_id
        try:
            args = json.loads(fc.arguments)
        except json.JSONDecodeError as e:
            # Malformed args from the model: surface error directly
            new_messages.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=call_id,
                    output=json.dumps({"exit": 2, "stdout": "", "stderr": f"invalid arguments: {e}"}),
                ),
            )
            continue
        result: dict[str, Any] | None = None
        if mcp_manager is not None and mcp_manager.is_mcp_tool(fn):
            try:
                result = await mcp_manager.call_tool(fn, args if isinstance(args, dict) else {})
            except Exception as e:
                result = {"exit": 127, "stdout": "", "stderr": f"mcp error: {e}"}
        else:
            result = {"exit": 127, "stdout": "", "stderr": f"unknown function: {fn}"}
        new_messages.append(
            FunctionCallOutput(
                type="function_call_output",
                call_id=call_id,
                output=json.dumps(result),
            ),
        )

    return new_messages, terminal_text



async def responses_followup_with_tool_outputs(
    client: openai.OpenAI,
    messages: list[Message],
    tool_outputs: list[FunctionCallOutput],
    mcp_manager: McpManager | None = None,
) -> tuple[list[Message], str | None]:
    instructions = SYSTEM_INSTRUCTIONS
    if mcp_manager is not None:
        extra = mcp_manager.instruction_block()
        if extra:
            instructions = f"{SYSTEM_INSTRUCTIONS}\n\n{extra}"
    input_payload = dump_messages_for_api(messages) + [t.model_dump(exclude_none=True) for t in tool_outputs]
    resp = _responses_create_with_retry(
        client,
        model=DEFAULT_MODEL,
        input=input_payload,
        instructions=instructions,
        stream=False,
        tool_choice="auto",
        store=False,
        tools=[*(mcp_manager.list_tools() if mcp_manager else [])],
    )
    new_messages: list[Message] = []
    terminal_text: str | None = None
    requires: list[ResponseFunctionToolCall] = []
    for item in resp.output:
        if isinstance(item, ResponseOutputMessage):
            text_parts = []
            for part in item.content:
                if isinstance(part, ResponseOutputText):
                    text_parts.append(part.text)
            combined = "\n".join([p for p in text_parts if p])
            if combined:
                terminal_text = (terminal_text + "\n" if terminal_text else "") + combined
                new_messages.append(AssistantMessage(role="assistant", content=combined))
        elif isinstance(item, ResponseFunctionToolCall):
            requires.append(item)
    for fc in requires:
        call_id = fc.call_id
        try:
            args = json.loads(fc.arguments)
        except json.JSONDecodeError as e:
            new_messages.append(FunctionCallOutput(type="function_call_output", call_id=call_id, output=json.dumps({"exit": 2, "stdout": "", "stderr": f"invalid arguments: {e}"})))
            continue
        fn = fc.name
        if mcp_manager is not None and mcp_manager.is_mcp_tool(fn):
            try:
                result = await mcp_manager.call_tool(fn, args if isinstance(args, dict) else {})
            except Exception as e:
                result = {"exit": 127, "stdout": "", "stderr": f"mcp error: {e}"}
        else:
            result = {"exit": 127, "stdout": "", "stderr": f"unknown function: {fn}"}
        new_messages.append(FunctionCallOutput(type="function_call_output", call_id=call_id, output=json.dumps(result)))
    return new_messages, terminal_text


async def main_async() -> None:
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")

    # Build unified ToolMap: load MCP servers (if present) and add a local exec server
    cfg_path_env = os.environ.get("MCP_CONFIG")
    cfg_path = Path(cfg_path_env) if cfg_path_env else (Path.cwd() / ".mcp.json")
    tools: dict[str, Any] = {}
    if cfg_path.exists():
        tools.update(load_mcp_file(str(cfg_path)))
    tools[LOCAL_EXEC_SERVER_NAME] = LocalExecServer(name=LOCAL_EXEC_SERVER_NAME)

    agent = await MiniCodex.start(model=DEFAULT_MODEL, tools=tools, system=SYSTEM_INSTRUCTIONS, tool_policy="auto")

    try:
        for line in sys.stdin:
            user = line.rstrip("\n")
            if not user:
                continue
            result = await agent.run(user)
            # Emit structured tool events as JSONL
            for evt in result.sequence:
                if evt.get("kind") == "tool_output":
                    print(json.dumps({
                        "ts": time.time(),
                        "tool": evt.get("name"),
                        "result": evt.get("result"),
                        "latency_ms": int(evt.get("latency").total_seconds() * 1000) if evt.get("latency") else None,
                        "error": evt.get("error"),
                    }, ensure_ascii=False))
            # Then assistant text
            if result.text:
                print(result.text)
    finally:
        await agent.close()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
