#!/usr/bin/env python3
"""Local proxy that adds authentication for an upstream TLS-inspecting proxy.

Used by Bazel to access BCR through Claude Code web's proxy infrastructure.
Reads upstream proxy configuration from https_proxy environment variable.

Runs in foreground - lifecycle managed by supervisor.

IMPORTANT: This module must not import any non-stdlib packages.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import ParseResult, urlparse

DEFAULT_STATE_DIR = Path.home() / ".cache" / "bazel-proxy"
DEFAULT_PORT = 18081
CREDENTIALS_FILE = "upstream_proxy"  # Relative to state_dir

log = logging.getLogger(__name__)


@dataclass
class CredentialCache:
    """Cached credentials with file mtime for invalidation."""

    proxy: ParseResult | None = None
    auth_header: str = ""
    mtime: float = 0


def setup_logging() -> None:
    """Configure logging to stdout (captured by supervisor)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_proxy_url(proxy_url: str) -> ParseResult:
    """Parse proxy URL, raising ValueError if invalid."""
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        raise ValueError(f"Could not parse host from {proxy_url}")
    return parsed


def get_upstream_proxy() -> ParseResult:
    """Get upstream proxy URL from environment, exit if not set."""
    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not proxy_url:
        sys.exit("Error: https_proxy environment variable not set")
    return parse_proxy_url(proxy_url)


def load_credentials(state_dir: Path, cache: CredentialCache) -> tuple[ParseResult, str]:
    """Load credentials from file, with caching based on file mtime.

    Returns (proxy, auth_header) tuple.
    Caches results until the credentials file is modified.
    """
    creds_file = state_dir / CREDENTIALS_FILE
    if not creds_file.exists():
        raise RuntimeError(f"Credentials file not found: {creds_file}")

    current_mtime = creds_file.stat().st_mtime

    # Return cached if file hasn't changed
    if cache.proxy is not None and current_mtime == cache.mtime:
        return cache.proxy, cache.auth_header

    # Reload from file
    proxy_url = creds_file.read_text().strip()
    if not proxy_url:
        raise RuntimeError(f"Credentials file is empty: {creds_file}")

    proxy = parse_proxy_url(proxy_url)
    auth_header = make_auth_header(proxy)

    # Update cache
    cache.proxy = proxy
    cache.auth_header = auth_header
    cache.mtime = current_mtime

    log.info("Loaded credentials for %s:%d", proxy.hostname, proxy.port or 80)
    return proxy, auth_header


def write_credentials(state_dir: Path, proxy_url: str) -> None:
    """Write credentials to file for the proxy to read."""
    creds_file = state_dir / CREDENTIALS_FILE
    creds_file.parent.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(proxy_url)


def make_auth_header(proxy: ParseResult) -> str:
    """Create Proxy-Authorization header from proxy credentials.

    Returns empty string if no credentials present.
    """
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
        # Client/server closed connection during transfer - normal for proxying
        pass
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
    upstream_reader, upstream_writer = await asyncio.open_connection(proxy.hostname, proxy.port or 80)

    try:
        connect_req = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n{auth_header}\r\n"
        )
        upstream_writer.write(connect_req.encode())
        await upstream_writer.drain()

        response_line = await upstream_reader.readline()
        if b"200" not in response_line:
            client_writer.write(response_line)
            while True:
                line = await upstream_reader.readline()
                client_writer.write(line)
                if line == b"\r\n":
                    break
            await client_writer.drain()
            return

        while (await upstream_reader.readline()) != b"\r\n":
            pass

        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer))
    finally:
        upstream_writer.close()
        await upstream_writer.wait_closed()


async def handle_client(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter, state_dir: Path, cache: CredentialCache
) -> None:
    """Handle incoming client connection.

    Loads fresh credentials for each connection from the credentials file.
    """
    try:
        request_line = await client_reader.readline()
        if not request_line:
            return

        parts = request_line.decode().split()
        if len(parts) < 2:
            return

        method, target = parts[0], parts[1]
        log.info("Request: %s %s", method, target)

        while (await client_reader.readline()) != b"\r\n":
            pass

        if method != "CONNECT":
            client_writer.close()
            return

        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = target, 443

        # Load credentials fresh (with caching based on file mtime)
        proxy, auth_header = load_credentials(state_dir, cache)
        await handle_connect(client_reader, client_writer, host, port, proxy, auth_header)
    except Exception as e:
        log.exception("Error handling client: %s", e)
    finally:
        client_writer.close()
        await client_writer.wait_closed()


async def run_server(host: str, port: int, state_dir: Path, cache: CredentialCache) -> None:
    """Run the proxy server.

    Writes initial credentials from environment, then reads from file for
    each connection (allowing credential refresh without restart).
    """
    # Write initial credentials from environment
    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not proxy_url:
        sys.exit("Error: https_proxy environment variable not set")
    write_credentials(state_dir, proxy_url)

    # Load once to log initial configuration
    proxy, _ = load_credentials(state_dir, cache)

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_client(reader, writer, state_dir, cache)

    server = await asyncio.start_server(on_connect, host, port)
    log.info("Listening on %s:%d", host, port)
    log.info("Forwarding to %s:%d", proxy.hostname, proxy.port or 80)
    log.info("Credentials from %s (auto-refreshes on file change)", state_dir / CREDENTIALS_FILE)

    async with server:
        await server.serve_forever()


def main() -> int:
    """Main entry point - runs in foreground under supervisor."""
    parser = argparse.ArgumentParser(description="Local proxy for Bazel BCR access (managed by supervisor)")
    parser.add_argument("--listen-host", default="127.0.0.1", help="Host to listen on")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="Directory for credentials file")
    args = parser.parse_args()

    setup_logging()
    cache = CredentialCache()

    try:
        asyncio.run(run_server(args.listen_host, args.listen_port, args.state_dir, cache))
    except KeyboardInterrupt:
        log.info("Shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
