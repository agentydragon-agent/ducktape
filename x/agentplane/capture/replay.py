"""Replay saved LiteLLM bodies through a tiny local HTTP server."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from x.agentplane.capture.records import ConnectionDroppedRecord, RequestRecord, ResponseChunkRecord


def _requests(path: Path) -> list[RequestRecord]:
    return [RequestRecord.model_validate_json(line) for line in path.read_text().splitlines()]


def _response_events(path: Path) -> list[ResponseChunkRecord | ConnectionDroppedRecord]:
    result: list[ResponseChunkRecord | ConnectionDroppedRecord] = []
    for line in path.read_text().splitlines():
        kind = json.loads(line).get("kind")
        if kind == "response_chunk":
            result.append(ResponseChunkRecord.model_validate_json(line))
        elif kind == "connection_dropped":
            result.append(ConnectionDroppedRecord.model_validate_json(line))
        else:
            raise ValueError(f"unexpected replay response record kind: {kind!r}")
    return result


@contextmanager
def serve[Server: ThreadingHTTPServer](server: Server) -> Iterator[Server]:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


class ReplayServer(ThreadingHTTPServer):
    """Serve each captured upstream response to the next matching request."""

    def __init__(self, fixture: Path):
        self.requests = _requests(fixture / "llm-requests.jsonl")
        chunks: dict[str, list[bytes]] = {}
        dropped: set[str] = set()
        for row in _response_events(fixture / "llm-responses.jsonl"):
            if isinstance(row, ResponseChunkRecord):
                chunks.setdefault(row.capture_request_id, []).append(row.body.encode("utf-8"))
            else:
                dropped.add(row.capture_request_id)
        self.responses = [
            (chunks.get(row.capture_request_id, []), row.capture_request_id in dropped) for row in self.requests
        ]
        if any(not chunks for chunks, _dropped in self.responses):
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
                chunks, disconnect_after_chunks = self.server.responses[index]  # type: ignore[attr-defined]
                payload = b"".join(chunks)
                content_type = "text/event-stream" if payload.startswith((b"event:", b"data:")) else "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                if not disconnect_after_chunks:
                    self.send_header("Content-Length", str(len(payload)))
                else:
                    self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                if disconnect_after_chunks:
                    self.connection.shutdown(2)  # SHUT_RDWR
                    self.connection.close()

        super().__init__(("127.0.0.1", 0), Handler)

    def assert_consumed(self) -> None:
        if self._next != len(self.requests):
            raise AssertionError(f"replay used {self._next} requests; fixture has {len(self.requests)}")
