from __future__ import annotations

import json
import os
import sys
import time
from shutil import which
from typing import Any, Literal

import openai
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from adgn_llm.mini_codex.mcp_manager import McpManager

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
    import subprocess

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

    cwd_val = cwd or os.getcwd()

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
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def _is_retryable(err: BaseException) -> bool:
    if isinstance(err, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(err, APIStatusError):
        # Only retry 5xx
        return isinstance(err.status_code, int) and err.status_code >= 500
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=0.5),
    stop=stop_after_attempt(API_MAX_RETRIES + 1),
    reraise=True,
)
def _responses_create_with_retry(client: openai.OpenAI, **params: Any):
    return client.responses.create(**params)


def responses_turn(
    client: openai.OpenAI, messages: list[Message], mcp_manager: McpManager | None = None,
) -> tuple[list[Message], str | None]:
    """Send a single non-streaming turn via Responses API.

    Returns (new_messages, terminal_text). If terminal_text is not None,
    print it to stdout for the user.
    """
    # Include MCP server descriptions in the instructions, if available
    instructions = SYSTEM_INSTRUCTIONS
    if mcp_manager is not None:
        try:
            extra = mcp_manager.instruction_block()
            if extra:
                instructions = f"{SYSTEM_INSTRUCTIONS}\n\n{extra}"
        except Exception:
            pass

    resp = _responses_create_with_retry(
        client,
        model=DEFAULT_MODEL,
        input=dump_messages_for_api(messages),
        instructions=instructions,
        stream=False,
        tool_choice="auto",
        store=False,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "shell.run",
                    "description": "Run a shell command in a sandbox and return exit code, stdout, stderr.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "array", "items": {"type": "string"}},
                            "cwd": {"type": "string"},
                            "timeout_ms": {"type": "integer"},
                        },
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                },
            },
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
        if fn == "shell.run":
            cmd = args.get("cmd")
            if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
                result = {"exit": 2, "stdout": "", "stderr": "invalid cmd"}
            else:
                timeout_ms = args.get("timeout_ms")
                to = (
                    DEFAULT_TIMEOUT_S
                    if not isinstance(timeout_ms, int)
                    else max(1, int(timeout_ms / 1000))
                )
                cwd_val = args.get("cwd") if isinstance(args.get("cwd"), str) else None
                try:
                    code, out, err = run_in_sandbox(cmd, timeout_s=to, cwd=cwd_val)
                    result = {"exit": code, "stdout": out, "stderr": err}
                except ExecError as e:
                    result = {"exit": 127, "stdout": "", "stderr": str(e)}
        elif fn.startswith("mcp:") and mcp_manager is not None:
            try:
                result = mcp_manager.call_tool(fn, args if isinstance(args, dict) else {})
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



def main() -> None:
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")
    client = openai_client()

    # MCP manager (Null Object if no servers configured or config missing)
    try:
        cfg_path = os.environ.get("MCP_CONFIG") or os.path.join(os.getcwd(), ".mcp.json")
        mcp_manager = McpManager.from_config(cfg_path)
    except Exception as e:
        print(f"[MCP disabled] {e}", file=sys.stderr)
        mcp_manager = McpManager.from_config(None)

    transcript: list[Message] = []

    for line in sys.stdin:
        user = line.rstrip("\n")
        if not user:
            continue
        transcript.append(UserMessage(role="user", content=user))

        # Iterate until the model no longer requires action in this turn.
        # We make at most N cycles per user input to avoid infinite loops.
        cycles = 0
        terminal_batch: list[str] = []
        run_results: list[dict[str, Any]] = []
        while cycles < MAX_CYCLES:
            cycles += 1
            new_msgs, terminal_text = responses_turn(client, transcript, mcp_manager)
            if terminal_text:
                terminal_batch.append(terminal_text)
            transcript.extend(new_msgs)

            # Collect run results only from this cycle
            for m in new_msgs:
                if isinstance(m, FunctionCallOutput):
                    try:
                        payload = json.loads(m.output or "{}")
                    except json.JSONDecodeError:
                        payload = {"malformed": True}
                    run_results.append(
                        {
                            "ts": time.time(),
                            "action": "shell.run",
                            "result": payload,
                        },
                    )

            # If no tool outputs were enqueued, assume turn done
            if not any(isinstance(m, FunctionCallOutput) for m in new_msgs):
                break

        # First emit JSONL for run results on stdout (machine-consumable)
        for rec in run_results:
            print(json.dumps(rec, ensure_ascii=False))

        # Then flush assistant text to terminal (human-friendly)
        if terminal_batch:
            print("\n".join(terminal_batch))

    if mcp_manager is not None:
        mcp_manager.close()


if __name__ == "__main__":
    main()
