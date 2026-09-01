"""Replay saved LiteLLM bodies through a tiny local HTTP server."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

from x.agentplane.capture.records import RequestRecord, ResponseChunkRecord


def _requests(path: Path) -> list[RequestRecord]:
    return [
        RequestRecord.model_validate_json(line) for line in path.read_text().splitlines() if '"kind":"request"' in line
    ]


def _response_chunks(path: Path) -> list[ResponseChunkRecord]:
    return [
        ResponseChunkRecord.model_validate_json(line)
        for line in path.read_text().splitlines()
        if '"kind":"response_chunk"' in line
    ]


class ReplayServer(ThreadingHTTPServer):
    """Serve each captured upstream response to the next matching request."""

    def __init__(self, fixture: Path):
        self.requests = _requests(fixture / "llm-requests.jsonl")
        chunks: dict[str, list[bytes]] = {}
        for row in _response_chunks(fixture / "llm-responses.jsonl"):
            chunks.setdefault(row.capture_request_id, []).append(row.body.encode("utf-8"))
        self.responses = [chunks.get(row.capture_request_id, []) for row in self.requests]
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
                if self.path != expected.path_query:
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
