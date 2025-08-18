import json
import os
import shutil

import subprocess
import sys
import time
import contextlib
from pathlib import Path

import pytest


from ._helpers import pick_free_port, read_line_json, send_line_json


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _send_line(w, obj: dict) -> None:
    w.write((json.dumps(obj) + "\n").encode("utf-8"))
    w.flush()


def _read_line(r, timeout: float) -> dict | None:
    import select

    fd = r.fileno()
    os.set_blocking(fd, False)
    buf = bytearray()
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            b = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not b:
            time.sleep(0.01)
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


@pytest.mark.skipif(shutil.which("jupyter") is None or shutil.which("jupyter-mcp-server") is None, reason="requires jupyter and jupyter-mcp-server on PATH")
def test_unsandbox_initialize_and_hello(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    nb_rel = Path(".mcp/test.ipynb")
    (ws / nb_rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / nb_rel).write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "kernelspec": {
                        "name": "python3",
                        "display_name": "Python 3",
                        "language": "python",
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        )
    )

    port = pick_free_port()
    token = f"test-{next(__import__('tempfile')._get_candidate_names())}"

    js_cmd = [
        "jupyter",
        "server",
        "--port",
        str(port),
        "--ip",
        "127.0.0.1",
        "--ServerApp.root_dir",
        str(ws),
        "--ServerApp.open_browser",
        "False",
        "--ServerApp.token",
        token,
        "--ServerApp.password",
        "",
        "--ServerApp.disable_check_xsrf",
        "True",
    ]
    js_out = (ws / "jupyter_server.out").open("wb")
    js_err = (ws / "jupyter_server.err").open("wb")
    js = subprocess.Popen(js_cmd, stdout=js_out, stderr=js_err)
    try:
        assert _wait_port(port, 15.0), "Jupyter server did not start"

        mcp_cmd = [
            "jupyter-mcp-server",
            "start",
            "--transport",
            "stdio",
            "--provider",
            "jupyter",
            "--document-url",
            f"http://127.0.0.1:{port}",
            "--document-id",
            str(nb_rel),
            "--document-token",
            token,
            "--runtime-url",
            f"http://127.0.0.1:{port}",
            "--runtime-token",
            token,
            "--start-new-runtime",
            "true",
        ]
        mcp = subprocess.Popen(
            mcp_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "unsandbox-smoke", "version": "0.0.1"},
                },
            }
            send_line_json(mcp.stdin, init)
            resp = read_line_json(mcp.stdout, 10.0)
            assert resp and resp.get("id") == 1 and "result" in resp, f"initialize failed: {resp}\nstderr:\n{(mcp.stderr.read() or b'').decode('utf-8', 'ignore')[-2000:]}"

            send_line_json(mcp.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            time.sleep(0.2)

            call = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "append_execute_code_cell",
                    "arguments": {"cell_source": "print('hello world')"},
                },
            }
            send_line_json(mcp.stdin, call)
            resp2 = read_line_json(mcp.stdout, 20.0)
            assert resp2 and resp2.get("id") == 2 and "result" in resp2, f"tool call failed: {resp2}\nstderr:\n{(mcp.stderr.read() or b'').decode('utf-8','ignore')[-2000:]}"

            result = resp2["result"]
            text_chunks = []
            try:
                sc = result.get("structuredContent")
                if sc and isinstance(sc.get("result"), list):
                    text_chunks.extend(map(str, sc["result"]))
            except Exception:
                pass
            try:
                content = result.get("content") or []
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text_chunks.append(str(c.get("text", "")))
            except Exception:
                pass
            joined = "\n".join(text_chunks)
            assert "hello world" in joined
        finally:
            with contextlib.suppress(Exception):
                mcp.terminate(); mcp.kill()
    finally:
        with contextlib.suppress(Exception):
            js.terminate(); js.kill()
        with contextlib.suppress(Exception):
            js_out.close(); js_err.close()
