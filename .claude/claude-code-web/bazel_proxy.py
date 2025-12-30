#!/usr/bin/env python3
"""Local proxy that adds authentication for an upstream TLS-inspecting proxy.

Used by Bazel to access BCR through Claude Code web's proxy infrastructure.
Reads upstream proxy configuration from https_proxy environment variable.
"""

import argparse
import asyncio
import base64
import os
import sys
from urllib.parse import ParseResult, urlparse


def get_upstream_proxy() -> ParseResult:
    """Get upstream proxy URL from environment, exit if not set."""
    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not proxy_url:
        sys.exit("Error: https_proxy environment variable not set")
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        sys.exit(f"Error: Could not parse host from {proxy_url}")
    return parsed


def make_auth_header(proxy: ParseResult) -> str:
    if not proxy.username:
        return ""
    creds = f"{proxy.username}:{proxy.password or ''}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Proxy-Authorization: Basic {encoded}\r\n"


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy data from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass  # Expected when peer closes connection
    finally:
        writer.close()
        await writer.wait_closed()


async def handle_connect(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
    proxy: ParseResult,
    auth_header: str,
) -> None:
    """Handle CONNECT by tunneling through upstream proxy."""
    upstream_reader, upstream_writer = await asyncio.open_connection(
        proxy.hostname, proxy.port or 80
    )

    try:
        # Send CONNECT with auth to upstream
        connect_req = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"{auth_header}\r\n"
        )
        upstream_writer.write(connect_req.encode())
        await upstream_writer.drain()

        # Read response headers
        response_line = await upstream_reader.readline()
        if b"200" not in response_line:
            # Forward error response to client
            client_writer.write(response_line)
            while True:
                line = await upstream_reader.readline()
                client_writer.write(line)
                if line == b"\r\n":
                    break
            await client_writer.drain()
            return

        # Connection established - consume remaining headers
        while (await upstream_reader.readline()) != b"\r\n":
            pass

        # Tell client connection is ready
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        # Bidirectional tunnel
        await asyncio.gather(
            pipe(client_reader, upstream_writer),
            pipe(upstream_reader, client_writer),
        )
    finally:
        upstream_writer.close()
        await upstream_writer.wait_closed()


async def handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    proxy: ParseResult,
    auth_header: str,
) -> None:
    """Handle incoming client connection."""
    try:
        # Read request line
        request_line = await client_reader.readline()
        if not request_line:
            return

        parts = request_line.decode().split()
        if len(parts) < 2:
            return

        method, target = parts[0], parts[1]

        # Consume remaining headers
        while (await client_reader.readline()) != b"\r\n":
            pass

        if method != "CONNECT":
            client_writer.close()
            return

        # Parse host:port
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = target, 443

        await handle_connect(client_reader, client_writer, host, port, proxy, auth_header)
    except Exception as e:
        print(f"Error handling client: {e}", file=sys.stderr)
    finally:
        client_writer.close()
        await client_writer.wait_closed()


async def run_server(host: str, port: int) -> None:
    proxy = get_upstream_proxy()
    auth_header = make_auth_header(proxy)

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_client(reader, writer, proxy, auth_header)

    server = await asyncio.start_server(on_connect, host, port)
    print(f"Bazel proxy listening on {host}:{port}")
    print(f"Forwarding to {proxy.hostname}:{proxy.port or 80}")

    async with server:
        await server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local proxy for Bazel BCR access")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=18081)
    args = parser.parse_args()

    asyncio.run(run_server(args.listen_host, args.listen_port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
