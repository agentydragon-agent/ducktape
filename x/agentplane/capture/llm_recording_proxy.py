"""Header-blind local LiteLLM proxy that records bodies and preserves response streaming."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from socket import SHUT_RDWR
from threading import Lock
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from x.agentplane.capture.records import ConnectionDroppedRecord, ProxyErrorRecord, RequestRecord, ResponseChunkRecord

_SAFE_HEADERS = frozenset({"content-type", "content-encoding", "accept", "user-agent"})
_FORBIDDEN_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie"})
Record = Callable[[RequestRecord | ResponseChunkRecord | ConnectionDroppedRecord | ProxyErrorRecord], None]


class BudgetExceededError(RuntimeError):
    """The live runner's explicit provider-call ceiling refused another request."""


def safe_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered not in _FORBIDDEN_HEADERS and lowered in _SAFE_HEADERS:
            result[lowered] = value
    return result


def recording_proxy(
    *, upstream: str, record: Record, disconnect_once_after_partial_prompt: str | None = None
) -> ThreadingHTTPServer:
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("upstream must be an absolute HTTP(S) origin")
    request_ids = count(1)
    request_ids_lock = Lock()
    disconnect_lock = Lock()
    disconnect_available = True

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:
            nonlocal disconnect_available
            with request_ids_lock:
                capture_request_id = f"llm-{next(request_ids)}"
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            disconnect_after_partial = False
            if disconnect_once_after_partial_prompt and disconnect_once_after_partial_prompt.encode() in body:
                # Session-title requests repeat the prompt but have no native tools. Drop the actual
                # harness turn instead, after its partial assistant content has reached the native client.
                is_harness_turn = bool(json.loads(body).get("tools"))
                with disconnect_lock:
                    if disconnect_available and is_harness_turn:
                        disconnect_after_partial = True
                        disconnect_available = False
            base_path = parsed.path.rstrip("/")
            target = (
                f"{parsed.scheme}://{parsed.netloc}{self.path}"
                if base_path and self.path.startswith(f"{base_path}/")
                else upstream.rstrip("/") + self.path
            )
            try:
                record(
                    RequestRecord(
                        kind="request",
                        capture_request_id=capture_request_id,
                        method="POST",
                        path_query=self.path,
                        body=body.decode("utf-8"),
                    )
                )
            except BudgetExceededError:
                self.send_error(429, "capture provider-call ceiling exceeded")
                return
            outgoing_headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "content-length"}
            }
            try:
                request = Request(target, data=body or None, headers=outgoing_headers, method="POST")
                with build_opener().open(request, timeout=120) as response:
                    self._relay(
                        capture_request_id,
                        response,
                        safe_headers(response.headers),
                        disconnect_after_partial=disconnect_after_partial,
                    )
            except HTTPError as error:
                self._relay_bytes(capture_request_id, error.code, error.read(), safe_headers(error.headers))
            except Exception as error:
                record(
                    ProxyErrorRecord(
                        kind="proxy_error", capture_request_id=capture_request_id, error_kind=type(error).__name__
                    )
                )
                self.send_error(502, "recording proxy upstream failure")

        def _begin(self, status: int, headers: dict[str, str]) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()

        def _relay(
            self, capture_request_id: str, response: Any, headers: dict[str, str], *, disconnect_after_partial: bool
        ) -> None:
            self._begin(response.status, headers)
            ordinal = 0
            while chunk := response.read1(65536):
                ordinal += 1
                record(
                    ResponseChunkRecord(
                        kind="response_chunk",
                        capture_request_id=capture_request_id,
                        ordinal=ordinal,
                        body=chunk.decode("utf-8"),
                    )
                )
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                if disconnect_after_partial and (b'"text_delta"' in chunk or b"response.output_text.delta" in chunk):
                    record(ConnectionDroppedRecord(kind="connection_dropped", capture_request_id=capture_request_id))
                    with suppress(OSError):
                        self.connection.shutdown(SHUT_RDWR)
                    self.connection.close()
                    return

        def _relay_bytes(self, capture_request_id: str, status: int, body: bytes, headers: dict[str, str]) -> None:
            self._begin(status, headers)
            record(
                ResponseChunkRecord(
                    kind="response_chunk", capture_request_id=capture_request_id, ordinal=1, body=body.decode("utf-8")
                )
            )
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
