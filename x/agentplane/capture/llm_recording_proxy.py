"""Header-blind local reverse proxy for correlation with LiteLLM traffic.

Forwarding temporarily sees request headers, but only a fixed safe subset reaches the
capture callback.  No full header map exists in any recordable object.
"""

from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

_SAFE_HEADERS = frozenset({"content-type", "content-encoding", "accept", "user-agent"})
_FORBIDDEN_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie"})
Record = Callable[[str, dict[str, Any]], None]


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
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            target = upstream.rstrip("/") + self.path
            record(
                "request",
                {"method": self.command, "path_query": self.path, "headers": safe_headers(self.headers), "body": body},
            )
            outgoing_headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "content-length"}
            }
            try:
                request = Request(target, data=body or None, headers=outgoing_headers, method=self.command)
                with build_opener().open(request, timeout=120) as response:
                    response_body = response.read()
                    safe = safe_headers(response.headers)
                    record("response", {"status": response.status, "headers": safe, "body": response_body})
                    self.send_response(response.status)
                    self.send_header("Content-Length", str(len(response_body)))
                    for key, value in safe.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(response_body)
            except Exception as error:  # error body must not capture upstream detail/credentials
                record("proxy_error", {"kind": type(error).__name__})
                self.send_error(502, "recording proxy upstream failure")

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
