"""Header-blind local reverse proxy for correlation with LiteLLM traffic.

Forwarding temporarily sees request headers, but only a fixed safe subset reaches the
capture callback.  No full header map exists in any recordable object.
"""

from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from threading import Lock
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

_SAFE_HEADERS = frozenset({"content-type", "content-encoding", "accept", "user-agent"})
_FORBIDDEN_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie"})
Record = Callable[[str, dict[str, Any]], None]


class BudgetExceededError(RuntimeError):
    """The live runner's explicit provider-call ceiling refused another request."""


def safe_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in _FORBIDDEN_HEADERS:
            continue
        if lowered in _SAFE_HEADERS:
            result[lowered] = value
    return result


def recording_proxy(*, upstream: str, record: Record) -> ThreadingHTTPServer:
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("upstream must be an absolute HTTP(S) origin")

    request_ids = count(1)
    request_ids_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            # BaseHTTPRequestHandler would log headers/paths in failure cases; never do that.
            return

        def do_GET(self) -> None:
            self._forward()

        def do_POST(self) -> None:
            self._forward()

        def do_PUT(self) -> None:
            self._forward()

        def do_PATCH(self) -> None:
            self._forward()

        def _forward(self) -> None:
            with request_ids_lock:
                capture_request_id = f"llm-{next(request_ids)}"
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            base_path = parsed.path.rstrip("/")
            if base_path and self.path.startswith(f"{base_path}/"):
                target = f"{parsed.scheme}://{parsed.netloc}{self.path}"
            else:
                target = upstream.rstrip("/") + self.path
            try:
                record(
                    "request",
                    {
                        "capture_request_id": capture_request_id,
                        "method": self.command,
                        "path_query": self.path,
                        "headers": safe_headers(self.headers),
                        "body": body,
                    },
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
                request = Request(target, data=body or None, headers=outgoing_headers, method=self.command)
                with build_opener().open(request, timeout=120) as response:
                    self._relay_response(
                        capture_request_id, response.status, safe_headers(response.headers), response.read()
                    )
            except HTTPError as error:
                self._relay_response(capture_request_id, error.code, safe_headers(error.headers), error.read())
            except Exception as error:  # error body must not capture upstream detail/credentials
                record("proxy_error", {"capture_request_id": capture_request_id, "kind": type(error).__name__})
                self.send_error(502, "recording proxy upstream failure")

        def _relay_response(
            self, capture_request_id: str, status: int, safe: dict[str, str], response_body: bytes
        ) -> None:
            record("response_chunk", {"capture_request_id": capture_request_id, "ordinal": 1, "body": response_body})
            record(
                "response",
                {"capture_request_id": capture_request_id, "status": status, "headers": safe, "body": response_body},
            )
            self.send_response(status)
            self.send_header("Content-Length", str(len(response_body)))
            for key, value in safe.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
