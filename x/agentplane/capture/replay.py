"""Replay saved LiteLLM bodies through a tiny local HTTP server."""

from __future__ import annotations

import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _body(record: dict[str, Any]) -> bytes:
    value = record["body"]
    if not isinstance(value, dict) or not isinstance(value.get("base64"), str):
        raise ValueError("fixture body is not base64 data")
    return base64.b64decode(value["base64"], validate=True)


class ReplayServer(ThreadingHTTPServer):
    """Serve each captured upstream response to the next matching request."""

    def __init__(self, fixture: Path):
        self.requests = [row for row in _rows(fixture / "llm-requests.jsonl") if row["kind"] == "request"]
        chunks: dict[str, list[bytes]] = {}
        for row in _rows(fixture / "llm-responses.jsonl"):
            if row["kind"] == "response_chunk":
                chunks.setdefault(str(row["capture_request_id"]), []).append(_body(row))
        self.responses = [chunks.get(str(row["capture_request_id"]), []) for row in self.requests]
        if any(not response for response in self.responses):
            raise ValueError("fixture has a request without captured response data")
        self.observed: list[dict[str, Any]] = []
        self._next = 0
        self._lock = Lock()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                with self.server._lock:  # type: ignore[attr-defined]
                    index = self.server._next  # type: ignore[attr-defined]
                    self.server._next += 1  # type: ignore[attr-defined]
                if index >= len(self.server.requests):  # type: ignore[attr-defined]
                    self.send_error(500, "unexpected replay request")
                    return
                expected = self.server.requests[index]  # type: ignore[attr-defined]
                if self.path != expected["path_query"]:
                    self.send_error(500, "replay request path mismatch")
                    return
                self.server.observed.append(  # type: ignore[attr-defined]
                    {"method": self.command, "path_query": self.path, "body": body}
                )
                chunks = self.server.responses[index]  # type: ignore[attr-defined]
                payload = b"".join(chunks)
                content_type = "text/event-stream" if payload.startswith((b"event:", b"data:")) else "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()

        super().__init__(("127.0.0.1", 0), Handler)

    def assert_consumed(self) -> None:
        if self._next != len(self.requests):
            raise AssertionError(f"replay used {self._next} requests; fixture has {len(self.requests)}")
