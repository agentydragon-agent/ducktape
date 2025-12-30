#!/usr/bin/env python3
"""Local proxy that adds authentication for an upstream TLS-inspecting proxy.

Used by Bazel to access BCR through Claude Code web's proxy infrastructure.
Reads upstream proxy configuration from https_proxy environment variable.

Usage:
    bazel_proxy.py [--listen-port PORT]
"""

import argparse
import base64
import os
import socket
import sys
import threading
from urllib.parse import urlparse


def parse_proxy_env() -> tuple[str, int, str, str]:
    """Parse upstream proxy from https_proxy environment variable."""
    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not proxy_url:
        print("Error: https_proxy environment variable not set", file=sys.stderr)
        sys.exit(1)

    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = parsed.port or 80
    user = parsed.username or ""
    password = parsed.password or ""

    if not host:
        print(f"Error: Could not parse host from {proxy_url}", file=sys.stderr)
        sys.exit(1)

    return host, port, user, password


def make_auth_header(user: str, password: str) -> str:
    """Create Proxy-Authorization header."""
    if not user:
        return ""
    creds = f"{user}:{password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Proxy-Authorization: Basic {encoded}\r\n"


def handle_connect(
    client_sock: socket.socket,
    target_host: str,
    target_port: int,
    upstream_host: str,
    upstream_port: int,
    auth_header: str,
) -> None:
    """Handle CONNECT request by tunneling through upstream proxy."""
    upstream = None
    try:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.connect((upstream_host, upstream_port))

        # Send CONNECT with auth to upstream
        connect_req = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"{auth_header}"
            f"\r\n"
        )
        upstream.sendall(connect_req.encode())

        # Read response
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = upstream.recv(4096)
            if not chunk:
                break
            response += chunk

        # Check if connection established
        if b"200" in response.split(b"\r\n")[0]:
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

            # Tunnel data bidirectionally
            def forward(src: socket.socket, dst: socket.socket) -> None:
                try:
                    while True:
                        data = src.recv(65536)
                        if not data:
                            break
                        dst.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            t1 = threading.Thread(target=forward, args=(client_sock, upstream))
            t2 = threading.Thread(target=forward, args=(upstream, client_sock))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        else:
            client_sock.sendall(response)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
    finally:
        if upstream:
            try:
                upstream.close()
            except Exception:
                pass
        try:
            client_sock.close()
        except Exception:
            pass


def handle_client(
    client_sock: socket.socket,
    upstream_host: str,
    upstream_port: int,
    auth_header: str,
) -> None:
    """Handle incoming client connection."""
    try:
        # Read the request
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client_sock.recv(4096)
            if not chunk:
                return
            request += chunk

        first_line = request.split(b"\r\n")[0].decode()
        parts = first_line.split()
        if len(parts) < 3:
            return

        method = parts[0]
        target = parts[1]

        if method == "CONNECT":
            # Parse host:port
            if ":" in target:
                host, port_str = target.rsplit(":", 1)
                port = int(port_str)
            else:
                host = target
                port = 443
            handle_connect(client_sock, host, port, upstream_host, upstream_port, auth_header)
        else:
            # Forward non-CONNECT requests (shouldn't happen for HTTPS)
            client_sock.close()

    except Exception as e:
        print(f"Error handling client: {e}", file=sys.stderr)
        try:
            client_sock.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Local proxy for Bazel BCR access")
    parser.add_argument("--listen-host", default="127.0.0.1", help="Host to listen on")
    parser.add_argument("--listen-port", type=int, default=18081, help="Port to listen on")
    args = parser.parse_args()

    upstream_host, upstream_port, upstream_user, upstream_pass = parse_proxy_env()
    auth_header = make_auth_header(upstream_user, upstream_pass)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(10)
    print(f"Bazel proxy listening on {args.listen_host}:{args.listen_port}")
    print(f"Forwarding to {upstream_host}:{upstream_port}")

    while True:
        client_sock, _ = server.accept()
        threading.Thread(
            target=handle_client,
            args=(client_sock, upstream_host, upstream_port, auth_header),
            daemon=True,
        ).start()


if __name__ == "__main__":
    sys.exit(main())
