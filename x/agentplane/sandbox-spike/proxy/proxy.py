import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY_BYTES = 1024
OPERATION_VALUE = "sandbox-proxy-identity-spike"
REQUEST_ID = re.compile(r"[0-9a-f]{32}")
UPSTREAM_URL = os.environ.get("UPSTREAM_URL")
CREDENTIAL_PATH = Path("/var/run/spike-credential/value")
CREDENTIAL_VERSION_PATH = Path("/var/run/spike-credential/version")
WORKLOAD_TOKEN_PATH = Path("/var/run/spike-identity/token")


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def upstream_request(workload_token: str, request_id: str) -> tuple[int, bytes]:
    if UPSTREAM_URL is None:
        raise RuntimeError("UPSTREAM_URL is required")
    request = urllib.request.Request(
        f"{UPSTREAM_URL}/fixed-operation",
        data=json.dumps({"operation": "echo", "value": OPERATION_VALUE}, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {read_file(CREDENTIAL_PATH)}",
            "Content-Type": "application/json",
            "X-Credential-Version": read_file(CREDENTIAL_VERSION_PATH),
            "X-Request-Nonce": request_id,
            "X-Request-Timestamp": str(int(time.time())),
            "X-Workload-Token": workload_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "sandbox-spike-proxy"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "unknown_operation"})

    def do_CONNECT(self) -> None:
        self.send_json(405, {"error": "forward_proxying_disabled"})

    def do_POST(self) -> None:
        if self.path == "/crash-for-test":
            if self.headers.get("Content-Length", "0") != "0":
                self.send_json(400, {"error": "unexpected_body"})
                return
            self.send_json(202, {"status": "terminating"})
            os._exit(42)
        if self.path != "/operate":
            self.send_json(404, {"error": "unknown_operation"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= MAX_BODY_BYTES:
                raise ValueError("invalid_body_size")
            payload = json.loads(self.rfile.read(content_length))
            if set(payload) != {"request_id", "value"}:
                raise ValueError("invalid_fields")
            if REQUEST_ID.fullmatch(payload["request_id"]) is None:
                raise ValueError("invalid_request_id")
            if payload["value"] != OPERATION_VALUE:
                raise ValueError("invalid_value")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self.send_json(400, {"error": str(error)})
            return
        try:
            status, body = upstream_request(read_file(WORKLOAD_TOKEN_PATH), payload["request_id"])
        except (OSError, RuntimeError, urllib.error.URLError):
            self.send_json(502, {"error": "upstream_unavailable"})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "present-token"])
    args = parser.parse_args()
    if args.command == "present-token":
        status, body = upstream_request(sys.stdin.read().strip(), os.urandom(16).hex())
        print(json.dumps({"status": status, "body": json.loads(body)}))
        return
    ThreadingHTTPServer(("0.0.0.0", 8081), ProxyHandler).serve_forever()


if __name__ == "__main__":
    main()
