"""CLI entry point for containerized MockEgressProxy.

Wraps MockEgressProxy with CLI args and an HTTP management API for CA cert
retrieval, readiness checks, and stats. Used as the entrypoint for the OCI image.

Management endpoints (on --mgmt-port, default 8081):
    GET /ready   — 200 when proxy is listening
    GET /ca.pem  — PEM-encoded CA certificate
    GET /stats   — JSON connection statistics
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import signal
import urllib.parse

from devinfra.claude.testing.mock_egress_proxy import EgressProxyConfig, MockEgressProxy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MockEgressProxy container entry point")
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--mgmt-port", type=int, default=8081, help="Management API port")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--upstream-proxy-url", help="Upstream proxy URL (http://user:pass@host:port)")
    parser.add_argument("--upstream-ca-bundle", help="Path to CA bundle for upstream proxy TLS")
    parser.add_argument("--no-verify-target-certs", action="store_true")
    return parser.parse_args()


def _parse_upstream_config(url: str, ca_bundle: str | None) -> EgressProxyConfig:
    """Parse upstream proxy URL into EgressProxyConfig."""
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        raise ValueError(f"Invalid upstream proxy URL: {url}")
    return EgressProxyConfig(
        host=parsed.hostname,
        port=parsed.port or 8080,
        username=urllib.parse.unquote(parsed.username) if parsed.username else None,
        password=urllib.parse.unquote(parsed.password) if parsed.password else None,
        ca_bundle=ca_bundle,
    )


def _build_mgmt_handler(proxy: MockEgressProxy) -> tuple[dict[str, bytes], dict[str, str]]:
    """Build response maps for the management HTTP server."""
    bodies = {"/ready": b"ok", "/ca.pem": proxy.ca_cert_pem}
    content_types = {"/ready": "text/plain", "/ca.pem": "application/x-pem-file", "/stats": "application/json"}
    return bodies, content_types


async def _handle_mgmt_request(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, proxy: MockEgressProxy
) -> None:
    """Handle a single HTTP request on the management port."""
    try:
        request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    except (TimeoutError, asyncio.IncompleteReadError):
        writer.close()
        return

    request_line = request.split(b"\r\n", 1)[0].decode()
    parts = request_line.split()
    path = parts[1] if len(parts) > 1 else "/"

    if path == "/ready":
        body = b"ok"
        content_type = "text/plain"
        status = "200 OK"
    elif path == "/ca.pem":
        body = proxy.ca_cert_pem
        content_type = "application/x-pem-file"
        status = "200 OK"
    elif path == "/stats":
        body = json.dumps(dataclasses.asdict(proxy.stats)).encode()
        content_type = "application/json"
        status = "200 OK"
    else:
        body = b"not found"
        content_type = "text/plain"
        status = "404 Not Found"

    header = f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n\r\n"
    writer.write(header.encode() + body)
    await writer.drain()
    writer.close()


async def _run(args: argparse.Namespace) -> None:
    upstream = None
    if args.upstream_proxy_url:
        upstream = _parse_upstream_config(args.upstream_proxy_url, args.upstream_ca_bundle)

    async with MockEgressProxy(
        listen_port=args.listen_port,
        listen_address="0.0.0.0",
        username=args.username,
        password=args.password,
        upstream_proxy=upstream,
        verify_target_certs=not args.no_verify_target_certs,
    ) as proxy:
        # Start management HTTP server
        mgmt_server = await asyncio.start_server(
            lambda r, w: _handle_mgmt_request(r, w, proxy), "0.0.0.0", args.mgmt_port
        )
        logger.info("Management API on port %d, proxy on port %d", args.mgmt_port, proxy.port)

        # Wait for SIGTERM/SIGINT
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()

        logger.info("Shutting down...")
        mgmt_server.close()
        await mgmt_server.wait_closed()


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
