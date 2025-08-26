import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import openai
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")
DEFAULT_TIMEOUT_S = int(os.getenv("DUCK_TIMEOUT_S", "30"))
TRUNCATE_BYTES = int(os.getenv("DUCK_TRUNCATE_BYTES", str(8 * 1024)))
SYSTEM_INSTRUCTIONS = os.getenv(
    "SYSTEM_INSTRUCTIONS",
    (
        "You are a code agent. Use the tool shell.run to execute commands. "
        "Respond with helpful, concise text."
    ),
)

BWRAP = os.getenv("BWRAP", "bwrap")
ALLOW_UNSHARE_NET = os.getenv("DUCK_UNSHARE_NET", "0") == "1"
API_MAX_RETRIES = int(os.getenv("DUCK_API_MAX_RETRIES", "2"))


class ExecError(Exception):
    pass


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 12] + "\n[TRUNCATED]"


def run_in_sandbox(
    cmd: List[str], timeout_s: int = DEFAULT_TIMEOUT_S, cwd: Optional[str] = None
) -> Tuple[int, str, str]:
    if sys.platform != "linux":
        raise ExecError("Sandbox requires Linux (bubblewrap)")
    # Check bwrap exists
    from shutil import which

    if which(BWRAP) is None:
        raise ExecError("bubblewrap (bwrap) not found in PATH")

    cwd = cwd or os.getcwd()

    argv: List[str] = [
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
        cwd,
        cwd,
        "--chdir",
        cwd,
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

    import subprocess

    p = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return (
            124,
            _truncate(out, TRUNCATE_BYTES),
            _truncate(err + "\n[TIMEOUT]", TRUNCATE_BYTES),
        )

    return (
        p.returncode,
        _truncate(out, TRUNCATE_BYTES),
        _truncate(err, TRUNCATE_BYTES),
    )


def openai_client() -> openai.OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    return (
        openai.OpenAI(api_key=api_key, base_url=base_url)
        if base_url
        else openai.OpenAI(api_key=api_key)
    )


def _responses_create_with_retry(client: openai.OpenAI, **params: Any):
    delay = 0.5
    attempts = API_MAX_RETRIES + 1
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            return client.responses.create(**params)
        except (APITimeoutError, APIConnectionError, RateLimitError) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except APIStatusError as e:
            # Retry 5xx once or twice
            last_err = e
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            if isinstance(status, int) and status >= 500 and i < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except Exception as e:
            # Non-retryable
            last_err = e
            raise
    if last_err:
        raise last_err


def responses_turn(
    client: openai.OpenAI, messages: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Send a single non-streaming turn via Responses API.

    Returns (new_messages, terminal_text). If terminal_text is not None,
    print it to stdout for the user.
    """
    resp = _responses_create_with_retry(
        client,
        model=DEFAULT_MODEL,
        input=messages,
        instructions=SYSTEM_INSTRUCTIONS,
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
            }
        ],
    )

    new_messages: List[Dict[str, Any]] = []
    terminal_text: Optional[str] = None

    # Collect assistant output items and action requirements
    output = resp.output
    # Each item is a dict-like; we only handle messages and function_call
    requires: List[Dict[str, Any]] = []
    for item in output:
        t = item.get("type")
        if t == "message":
            # Print assistant text; also add to transcript
            text_parts = []
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "input_text"):
                    text_parts.append(part.get("text", ""))
            combined = "\n".join([p for p in text_parts if p])
            terminal_text = (terminal_text + "\n" if terminal_text else "") + combined
            new_messages.append({"role": "assistant", "content": combined})
        elif t == "function_call":
            requires.append(item)
        # ignore other item types for MVP

    # Execute required tool calls and enqueue function_call_output
    for fc in requires:
        fn = (fc.get("function") or {}).get("name") or fc.get("name")
        call_id = fc.get("call_id") or fc.get("id")
        args_str = (
            (fc.get("function") or {}).get("arguments") or fc.get("arguments") or "{}"
        )
        try:
            args = json.loads(args_str)
        except Exception:
            args = {}
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
                cwd = args.get("cwd") if isinstance(args.get("cwd"), str) else None
                try:
                    code, out, err = run_in_sandbox(cmd, timeout_s=to, cwd=cwd)
                    result = {"exit": code, "stdout": out, "stderr": err}
                except ExecError as e:
                    result = {"exit": 127, "stdout": "", "stderr": str(e)}
            new_messages.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                }
            )

    return new_messages, terminal_text


def emit_jsonl_stdout(obj: Dict[str, Any]) -> None:
    # Write JSONL to stdout; keep assistant text readable over it by printing later
    print(json.dumps(obj, ensure_ascii=False))


def main() -> None:
    print("mini-codex ready. Ctrl-D to exit. Type your task and press Enter.")
    client = openai_client()

    transcript: List[Dict[str, Any]] = []

    for line in sys.stdin:
        user = line.rstrip("\n")
        if not user:
            continue
        transcript.append({"role": "user", "content": user})

        # Iterate until the model no longer requires action in this turn.
        # We make at most N cycles per user input to avoid infinite loops.
        cycles = 0
        MAX_CYCLES = 8
        terminal_batch: List[str] = []
        run_results: List[Dict[str, Any]] = []
        while cycles < MAX_CYCLES:
            cycles += 1
            new_msgs, terminal_text = responses_turn(client, transcript)
            if terminal_text:
                terminal_batch.append(terminal_text)
            transcript.extend(new_msgs)

            # Collect run results only from this cycle
            for m in new_msgs:
                if m.get("type") == "function_call_output":
                    try:
                        payload = json.loads(m.get("output", "{}"))
                    except Exception:
                        payload = {"malformed": True}
                    run_results.append(
                        {
                            "ts": time.time(),
                            "action": "shell.run",
                            "result": payload,
                        }
                    )

            # If no tool outputs were enqueued, assume turn done
            if not any(m.get("type") == "function_call_output" for m in new_msgs):
                break

        # First emit JSONL for run results on stdout (machine-consumable)
        for rec in run_results:
            emit_jsonl_stdout(rec)

        # Then flush assistant text to terminal (human-friendly)
        if terminal_batch:
            print("\n".join(terminal_batch))


if __name__ == "__main__":
    main()
