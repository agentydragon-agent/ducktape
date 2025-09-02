#!/usr/bin/env python3
"""
MCP server: Execute arbitrary commands inside a specific Docker container.

Startup configuration (environment variables):
- DOCKER_CONTAINER (required): container name or ID to exec into
- DOCKER_HOST (optional): target engine (e.g., ssh://user@host, tcp://host:2375)
- DEFAULT_TIMEOUT_SECS (optional, float): default timeout if tool argument not provided (e.g., "60")
- USE_CONTAINER_TIMEOUT_WRAPPER (optional, "1"/"0"): if "1" (default), wrap the command with `timeout -s TERM <secs>` inside the container for reliable timeouts
- DOCKER_DEFAULT_CWD (optional): default working directory inside the container when cwd is not provided to the tool

Tool: docker.exec
- cmd: list[str]              required. argv vector to execute
- cwd: str | None             optional working directory inside container (overrides DOCKER_DEFAULT_CWD)
- env: dict[str,str] | None   optional environment overrides
- user: str | None            optional user (e.g., "root" or "1000:1000")
- tty: bool                   optional. default False
- shell: bool                 optional. if True, run via sh -lc "..." (default False)
- timeout_secs: float | None  optional; overrides DEFAULT_TIMEOUT_SECS

Behavior:
- Returns JSON with exit_code, timed_out, stdout, stderr (stdout/stderr are captured)
- Note: For simplicity over stdio, live streaming logs are not sent; callers receive full output on completion

Note on timeouts:
- Docker Engine API doesn't provide an "exec stop" primitive. To enforce timeouts reliably,
  we default to wrapping the command with `timeout -s TERM <secs>` inside the container when
  USE_CONTAINER_TIMEOUT_WRAPPER=1. If the container lacks `timeout`, set this env to 0 and
  be aware timeouts will be best-effort (we stop reading and report timed_out=True, but the
  process may continue running inside the container).
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import threading
from dataclasses import dataclass
from time import monotonic
from typing import Any, Dict, Iterator, List, Optional, Tuple

import docker
from docker.errors import APIError, NotFound

import mcp.types as types
from mcp.server.lowlevel import Server


app = Server("docker-exec-mcp")

# Global Docker client and container ref
_DOCKER_CLIENT: docker.DockerClient | None = None
_CONTAINER_REF: str | None = None
_DEFAULT_TIMEOUT: float | None = None
_DEFAULT_CWD: str | None = os.environ.get("DOCKER_DEFAULT_CWD")
_USE_TIMEOUT_WRAPPER: bool = os.environ.get("USE_CONTAINER_TIMEOUT_WRAPPER", "1") != "0"


def _init_docker() -> None:
    global _DOCKER_CLIENT, _CONTAINER_REF, _DEFAULT_TIMEOUT
    if _DOCKER_CLIENT is None:
        _DOCKER_CLIENT = docker.from_env()
    if not _CONTAINER_REF:
        _CONTAINER_REF = os.environ.get("DOCKER_CONTAINER")
        if not _CONTAINER_REF:
            raise RuntimeError("DOCKER_CONTAINER env var is required")
    if _DEFAULT_TIMEOUT is None:
        v = os.environ.get("DEFAULT_TIMEOUT_SECS")
        _DEFAULT_TIMEOUT = float(v) if v else None


def _shell_wrap(cmd: List[str]) -> str:
    return shlex.join(cmd)


@dataclass
class ExecResult:
    exit_code: Optional[int]
    timed_out: bool
    stdout: str
    stderr: str


def _iter_stream_demux(client: docker.DockerClient, exec_id: str) -> Iterator[Tuple[bytes | None, bytes | None]]:
    api = client.api
    return api.exec_start(exec_id, stream=True, demux=True)  # type: ignore[return-value]


def _build_exec_cmd(
    base_cmd: List[str], *, shell: bool, timeout_secs: Optional[float]
) -> List[str] | str:
    if _USE_TIMEOUT_WRAPPER and timeout_secs and timeout_secs > 0:
        timeout_arg = f"timeout -s TERM {int(timeout_secs)}"
        if shell:
            return f"{timeout_arg} {_shell_wrap(base_cmd)}"
        return ["sh", "-lc", f"{timeout_arg} {_shell_wrap(base_cmd)}"]
    if shell:
        return _shell_wrap(base_cmd)
    return base_cmd


async def _docker_exec(
    *,
    cmd: List[str],
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    user: Optional[str],
    tty: bool,
    shell: bool,
    timeout_secs: Optional[float],
) -> ExecResult:
    _init_docker()
    assert _DOCKER_CLIENT is not None
    assert _CONTAINER_REF is not None

    container = None
    try:
        container = _DOCKER_CLIENT.containers.get(_CONTAINER_REF)
    except NotFound as e:
        raise RuntimeError(f"Container not found: {_CONTAINER_REF}") from e

    effective_timeout = timeout_secs if timeout_secs is not None else _DEFAULT_TIMEOUT
    if cwd is None:
        cwd = _DEFAULT_CWD

    prepared_cmd = _build_exec_cmd(cmd, shell=shell, timeout_secs=effective_timeout)

    if shell and not (
        isinstance(prepared_cmd, list) and prepared_cmd[:2] == ["sh", "-lc"]
    ) and not isinstance(prepared_cmd, list):
        exec_create_cmd: List[str] | str = ["sh", "-lc", prepared_cmd]  # type: ignore[list-item]
    else:
        exec_create_cmd = prepared_cmd

    exec_id = _DOCKER_CLIENT.api.exec_create(
        container=_CONTAINER_REF,
        cmd=exec_create_cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=tty,
        user=user,
        workdir=cwd,
        environment=env,
    )["Id"]

    stdout_buf = bytearray()
    stderr_buf = bytearray()

    def reader() -> None:
        try:
            for out_err in _iter_stream_demux(_DOCKER_CLIENT, exec_id):  # type: ignore[arg-type]
                if not isinstance(out_err, tuple):
                    if out_err:  # type: ignore[truthy-bool]
                        stdout_buf.extend(out_err)  # type: ignore[arg-type]
                    continue
                out_b, err_b = out_err
                if out_b:
                    stdout_buf.extend(out_b)
                if err_b:
                    stderr_buf.extend(err_b)
        finally:
            pass

    thread = threading.Thread(target=reader, name="docker-exec-reader", daemon=True)
    thread.start()

    deadline = None
    if effective_timeout and effective_timeout > 0:
        deadline = monotonic() + float(effective_timeout)

    # Busy-wait until thread finishes or deadline
    timed_out = False
    while thread.is_alive():
        await asyncio.sleep(0.05)
        if deadline is not None and monotonic() >= deadline:
            timed_out = True
            break

    if timed_out:
        # We cannot reliably kill the exec unless wrapper handled it; return best-effort
        pass

    # Ensure thread completion (or small join)
    thread.join(timeout=1.0)

    try:
        inspect = _DOCKER_CLIENT.api.exec_inspect(exec_id)
        exit_code = inspect.get("ExitCode")
    except APIError:
        exit_code = None

    return ExecResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout_buf.decode(errors="replace"),
        stderr=stderr_buf.decode(errors="replace"),
    )


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="docker_exec",
            description="Execute a command inside the configured Docker container and return stdout/stderr/exit_code.",
            inputSchema={
                "type": "object",
                "required": ["cmd"],
                "properties": {
                    "cmd": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "env": {"type": "object", "additionalProperties": {"type": "string"}},
                    "user": {"type": "string"},
                    "tty": {"type": "boolean", "default": False},
                    "shell": {"type": "boolean", "default": False},
                    "timeout_secs": {"type": "number", "minimum": 0},
                },
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
    if name != "docker_exec":
        raise ValueError(f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be object")
    cmd = arguments.get("cmd") or []
    if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        raise ValueError("cmd must be array of strings")
    cwd = arguments.get("cwd")
    env = arguments.get("env")
    user = arguments.get("user")
    tty = bool(arguments.get("tty", False))
    shell = bool(arguments.get("shell", False))
    timeout_secs = arguments.get("timeout_secs")

    result = await _docker_exec(
        cmd=cmd, cwd=cwd, env=env, user=user, tty=tty, shell=shell, timeout_secs=timeout_secs
    )
    payload = {
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    return [types.TextContent(type="text", text=json.dumps(payload))]


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


def main() -> None:
    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
