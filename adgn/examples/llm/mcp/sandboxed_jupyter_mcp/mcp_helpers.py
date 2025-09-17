from collections.abc import Callable
import json
import os
import time
from typing import Any


def send_line_json(w, obj: dict) -> None:
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def read_line_json(r, timeout: float) -> dict | None:
    fd = r.fileno()
    os.set_blocking(fd, False)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            b = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        if not b:
            time.sleep(0.02)
            continue
        if b == b"\n":
            break
        buf.extend(b)
    if not buf:
        return None
    try:
        return json.loads(bytes(buf).decode("utf-8", errors="ignore").rstrip("\r"))
    except Exception:
        return None


def wait_for(
    stdout,
    predicate: Callable[[dict], bool],
    total_timeout: float,
) -> dict | None:
    deadline = time.time() + total_timeout
    while time.time() < deadline:
        m = read_line_json(stdout, 1.0)
        if not m:
            continue
        if predicate(m):
            return m
    return None


def wait_for_id(stdout, msg_id: int, total_timeout: float) -> dict | None:
    return wait_for(
        stdout,
        lambda m: m.get("id") == msg_id and ("result" in m or "error" in m),
        total_timeout,
    )


def initialize(
    stdio: tuple[Any, Any],
    *,
    protocol_version: str = "2025-06-18",
    client_info: dict[str, str] | None = None,
    timeout: float = 25.0,
) -> dict:
    stdin, stdout = stdio
    client_info = client_info or {"name": "pytest", "version": "0.0.1"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "clientInfo": client_info,
        },
    }
    send_line_json(stdin, init)
    resp = wait_for_id(stdout, 1, timeout)
    if not (resp and "result" in resp):
        raise AssertionError(f"initialize failed: {resp}")
    # acknowledge ready
    send_line_json(stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    time.sleep(0.2)
    return resp["result"]


def call_tool(
    stdio: tuple[Any, Any],
    name: str,
    arguments: dict[str, Any],
    *,
    timeout: float = 60.0,
    msg_id: int = 2,
) -> dict:
    stdin, stdout = stdio
    call = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    send_line_json(stdin, call)
    resp = wait_for_id(stdout, msg_id, timeout)
    if not (resp and "result" in resp):
        raise AssertionError(f"tool call failed: {resp}")
    return resp["result"]


def exec_code(
    stdio: tuple[Any, Any],
    code: str,
    *,
    timeout: float = 60.0,
    msg_id: int = 2,
) -> dict:
    return call_tool(
        stdio,
        "append_execute_code_cell",
        {"cell_source": code},
        timeout=timeout,
        msg_id=msg_id,
    )
